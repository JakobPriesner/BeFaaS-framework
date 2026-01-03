#!/usr/bin/env node

/**
 * Pre-register users in Redis before running Artillery benchmarks.
 * This script runs inside the Docker container on the workload EC2.
 *
 * Environment variables:
 *   REDIS_ENDPOINT - Redis connection URL (redis://default:password@host:port)
 *   AUTH_MODE - Authentication mode (none, service-integrated-manual)
 */

const fs = require('fs');
const net = require('net');
const crypto = require('crypto');

const usersFile = '/workload/users.csv';
const BCRYPT_ROUNDS = parseInt(process.env.BCRYPT_ROUNDS, 10) || 10;

/**
 * Parse Redis URL to get connection details
 */
function parseRedisUrl(url) {
  const match = url.match(/redis:\/\/([^:]*):([^@]*)@([^:]+):(\d+)/);
  if (!match) {
    throw new Error(`Invalid Redis URL format: ${url}`);
  }
  return {
    username: match[1] || 'default',
    password: match[2],
    host: match[3],
    port: parseInt(match[4], 10)
  };
}

/**
 * Parse users.csv file
 */
function parseUsersCSV() {
  const content = fs.readFileSync(usersFile, 'utf8');
  const lines = content.trim().split('\n');
  const header = lines[0].split(',');

  const userNameIndex = header.indexOf('userName');
  const passwordIndex = header.indexOf('password');

  if (userNameIndex === -1 || passwordIndex === -1) {
    throw new Error('users.csv must have userName and password columns');
  }

  const users = [];
  for (let i = 1; i < lines.length; i++) {
    const fields = lines[i].split(',');
    if (fields.length > Math.max(userNameIndex, passwordIndex)) {
      users.push({
        userName: fields[userNameIndex],
        password: fields[passwordIndex]
      });
    }
  }

  return users;
}

/**
 * Simple bcrypt hash using bcryptjs (available in container via npm)
 */
async function hashPassword(password) {
  return new Promise((resolve, reject) => {
    try {
      const bcrypt = require('bcryptjs');
      bcrypt.hash(password, BCRYPT_ROUNDS, (err, hash) => {
        if (err) reject(err);
        else resolve(hash);
      });
    } catch (e) {
      // Fallback if bcryptjs not available
      const salt = `$2a$${BCRYPT_ROUNDS}$` + crypto.randomBytes(16).toString('base64').substring(0, 22);
      const hash = salt + crypto.createHash('sha256').update(password + salt).digest('base64').substring(0, 31);
      resolve(hash);
    }
  });
}

/**
 * Redis client using RESP protocol
 */
class RedisClient {
  constructor(host, port, password) {
    this.host = host;
    this.port = port;
    this.password = password;
    this.socket = null;
  }

  async connect() {
    return new Promise((resolve, reject) => {
      this.socket = new net.Socket();
      this.socket.setEncoding('utf8');
      this.socket.setTimeout(30000);

      this.socket.connect(this.port, this.host, async () => {
        if (this.password) {
          try {
            await this.auth(this.password);
          } catch (error) {
            reject(new Error(`Redis AUTH failed: ${error.message}`));
            return;
          }
        }
        resolve();
      });

      this.socket.on('error', reject);
      this.socket.on('timeout', () => reject(new Error('Connection timeout')));
    });
  }

  sendCommand(args) {
    return new Promise((resolve, reject) => {
      let cmd = `*${args.length}\r\n`;
      for (const arg of args) {
        const strArg = String(arg);
        cmd += `$${Buffer.byteLength(strArg)}\r\n${strArg}\r\n`;
      }

      let response = '';
      const onData = (data) => {
        response += data;
        try {
          const result = this.parseResponse(response);
          if (result.complete) {
            this.socket.removeListener('data', onData);
            if (result.error) {
              reject(new Error(result.value));
            } else {
              resolve(result.value);
            }
          }
        } catch (e) {
          // Response incomplete, wait for more data
        }
      };

      this.socket.on('data', onData);
      this.socket.write(cmd);
    });
  }

  parseResponse(data) {
    const type = data[0];
    const endIdx = data.indexOf('\r\n');
    if (endIdx === -1) return { complete: false };

    switch (type) {
      case '+':
        return { complete: true, value: data.substring(1, endIdx) };
      case '-':
        return { complete: true, error: true, value: data.substring(1, endIdx) };
      case ':':
        return { complete: true, value: parseInt(data.substring(1, endIdx), 10) };
      case '$':
        const len = parseInt(data.substring(1, endIdx), 10);
        if (len === -1) return { complete: true, value: null };
        const valueStart = endIdx + 2;
        const valueEnd = valueStart + len;
        if (data.length < valueEnd + 2) return { complete: false };
        return { complete: true, value: data.substring(valueStart, valueEnd) };
      case '*':
        return { complete: true, value: 'OK' };
      default:
        return { complete: true, value: data };
    }
  }

  async auth(password) {
    return this.sendCommand(['AUTH', password]);
  }

  async set(key, value) {
    return this.sendCommand(['SET', key, JSON.stringify(value)]);
  }

  async exists(key) {
    const result = await this.sendCommand(['EXISTS', key]);
    return result === 1;
  }

  close() {
    if (this.socket) {
      this.socket.end();
    }
  }
}

async function registerUser(redis, userName, password, authMode) {
  const userKey = `user:${userName}`;

  const existing = await redis.exists(userKey);
  if (existing) {
    return 'exists';
  }

  let userData;
  if (authMode === 'none') {
    userData = { password };
  } else if (authMode === 'service-integrated-manual') {
    const passwordHash = await hashPassword(password);
    userData = {
      userName,
      passwordHash,
      createdAt: new Date().toISOString()
    };
  } else {
    userData = { password };
  }

  await redis.set(userKey, userData);
  return 'registered';
}

async function main() {
  const redisEndpoint = process.env.REDIS_ENDPOINT;
  const authMode = process.env.AUTH_MODE || 'none';

  if (!redisEndpoint) {
    console.log('REDIS_ENDPOINT not set, skipping preregistration');
    process.exit(0);
  }

  console.log('='.repeat(60));
  console.log('  Pre-registering Users in Redis');
  console.log('='.repeat(60));
  console.log(`Auth mode: ${authMode}`);

  // Parse users
  console.log('\nReading users from users.csv...');
  const users = parseUsersCSV();
  console.log(`Found ${users.length} users to register`);

  // Parse Redis URL
  const redisConfig = parseRedisUrl(redisEndpoint);
  console.log(`Redis host: ${redisConfig.host}:${redisConfig.port}`);

  // Connect to Redis
  console.log('\nConnecting to Redis...');
  const redis = new RedisClient(redisConfig.host, redisConfig.port, redisConfig.password);
  await redis.connect();
  console.log('Connected to Redis');

  // Register users
  console.log(`\nRegistering users...`);
  let registered = 0;
  let alreadyExists = 0;
  let failed = 0;

  for (let i = 0; i < users.length; i++) {
    const user = users[i];
    try {
      const result = await registerUser(redis, user.userName, user.password, authMode);
      if (result === 'registered') registered++;
      else if (result === 'exists') alreadyExists++;
    } catch (error) {
      failed++;
      if (failed <= 5) {
        console.error(`Failed to register ${user.userName}: ${error.message}`);
      }
    }

    if ((i + 1) % 100 === 0 || i === users.length - 1) {
      process.stdout.write(`\rProgress: ${i + 1}/${users.length} (${Math.round((i + 1) / users.length * 100)}%)`);
    }
  }

  console.log('\n');
  redis.close();

  console.log('Results:');
  console.log(`  Registered: ${registered}`);
  console.log(`  Already existed: ${alreadyExists}`);
  console.log(`  Failed: ${failed}`);
  console.log('='.repeat(60));

  if (failed > 0 && failed === users.length) {
    process.exit(1);
  }
}

main().catch(error => {
  console.error('Error:', error.message);
  process.exit(1);
});