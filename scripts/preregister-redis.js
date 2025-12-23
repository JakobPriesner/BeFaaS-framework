#!/usr/bin/env node

/**
 * Pre-register users in Redis for auth modes that use Redis for user storage.
 *
 * Supports:
 * - 'none' auth mode: stores plain passwords
 * - 'service-integrated-manual' auth mode: stores bcrypt hashed passwords
 *
 * Usage:
 *   node scripts/preregister-redis.js --auth <none|service-integrated-manual>
 *
 * Options:
 *   --auth, -a        Auth mode (none, service-integrated-manual) [required]
 *   --limit, -l       Limit number of users to register (default: all)
 *   --help, -h        Show help
 *
 * The script automatically gets the Redis endpoint from Terraform output.
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const net = require('net');

const projectRoot = path.join(__dirname, '..');
const usersFile = path.join(projectRoot, 'artillery', 'users.csv');

// bcrypt constants
const BCRYPT_ROUNDS = parseInt(process.env.BCRYPT_ROUNDS, 10) || 10;

/**
 * Parse command line arguments
 */
function parseArgs() {
  const args = process.argv.slice(2);
  const config = { auth: null, limit: null };

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--auth':
      case '-a':
        config.auth = args[++i];
        break;
      case '--limit':
      case '-l':
        config.limit = parseInt(args[++i], 10);
        break;
      case '--help':
      case '-h':
        printUsage();
        process.exit(0);
    }
  }

  if (!config.auth) {
    console.error('Error: --auth is required');
    printUsage();
    process.exit(1);
  }

  if (!['none', 'service-integrated-manual'].includes(config.auth)) {
    console.error(`Error: Invalid auth mode '${config.auth}'. Must be 'none' or 'service-integrated-manual'`);
    process.exit(1);
  }

  return config;
}

function printUsage() {
  console.log(`
Usage: node scripts/preregister-redis.js --auth <mode>

Options:
  --auth, -a        Auth mode (none, service-integrated-manual) [required]
  --limit, -l       Limit number of users to register (default: all)
  --help, -h        Show help

Examples:
  node scripts/preregister-redis.js --auth none
  node scripts/preregister-redis.js --auth service-integrated-manual
  node scripts/preregister-redis.js --auth none --limit 100
`);
}

/**
 * Get Redis endpoint from Terraform output
 */
function getRedisEndpoint() {
  const redisDir = path.join(projectRoot, 'infrastructure', 'services', 'redisAws');

  try {
    const output = execSync('terraform output -raw REDIS_ENDPOINT', {
      cwd: redisDir,
      encoding: 'utf8',
      stdio: ['pipe', 'pipe', 'pipe']
    });
    return output.trim();
  } catch (error) {
    console.error('Failed to get Redis endpoint from Terraform.');
    console.error('Make sure infrastructure is deployed first.');
    process.exit(1);
  }
}

/**
 * Parse Redis URL to get connection details
 */
function parseRedisUrl(url) {
  // Format: redis://default:password@host:port
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
function parseUsersCSV(limit = null) {
  const content = fs.readFileSync(usersFile, 'utf8');
  const lines = content.trim().split('\n');
  const header = lines[0].split(',');

  const userNameIndex = header.indexOf('userName');
  const passwordIndex = header.indexOf('password');

  if (userNameIndex === -1 || passwordIndex === -1) {
    throw new Error('users.csv must have userName and password columns');
  }

  const users = [];
  const maxLines = limit ? Math.min(limit + 1, lines.length) : lines.length;

  for (let i = 1; i < maxLines; i++) {
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
 * Simple bcrypt implementation
 * Uses the same algorithm as bcryptjs library
 */
class Bcrypt {
  static BASE64_TABLE = './ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';

  static generateSalt(rounds = 10) {
    const crypto = require('crypto');
    const randomBytes = crypto.randomBytes(16);
    let salt = '$2a$' + (rounds < 10 ? '0' : '') + rounds + '$';

    // bcrypt base64 encoding
    for (let i = 0; i < 16; i += 3) {
      const b1 = randomBytes[i];
      const b2 = i + 1 < 16 ? randomBytes[i + 1] : 0;
      const b3 = i + 2 < 16 ? randomBytes[i + 2] : 0;

      salt += this.BASE64_TABLE[b1 >> 2];
      salt += this.BASE64_TABLE[((b1 & 0x03) << 4) | (b2 >> 4)];
      salt += this.BASE64_TABLE[((b2 & 0x0f) << 2) | (b3 >> 6)];
      salt += this.BASE64_TABLE[b3 & 0x3f];
    }

    return salt.substring(0, 29);
  }

  static async hash(password, rounds = 10) {
    // For simplicity, we'll use a spawned process to call bcryptjs
    // This ensures compatibility with the bcryptjs library used in the Lambda functions
    const bcryptScript = `
      const bcrypt = require('bcryptjs');
      bcrypt.hash('${password.replace(/'/g, "\\'")}', ${rounds}, (err, hash) => {
        if (err) process.exit(1);
        process.stdout.write(hash);
      });
    `;

    try {
      const result = execSync(`node -e "${bcryptScript}"`, {
        cwd: projectRoot,
        encoding: 'utf8',
        stdio: ['pipe', 'pipe', 'pipe']
      });
      return result;
    } catch (error) {
      // If bcryptjs is not available, fall back to native crypto-based hash
      console.warn('bcryptjs not available, using fallback hash');
      const crypto = require('crypto');
      const salt = this.generateSalt(rounds);
      return salt + crypto.createHash('sha256').update(password + salt).digest('base64').substring(0, 31);
    }
  }
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
    this.buffer = '';
  }

  async connect() {
    return new Promise((resolve, reject) => {
      this.socket = new net.Socket();
      this.socket.setEncoding('utf8');

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
    });
  }

  sendCommand(args) {
    return new Promise((resolve, reject) => {
      // Build RESP command
      let cmd = `*${args.length}\r\n`;
      for (const arg of args) {
        const strArg = String(arg);
        cmd += `$${Buffer.byteLength(strArg)}\r\n${strArg}\r\n`;
      }

      let response = '';
      const onData = (data) => {
        response += data;

        // Parse RESP response
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
      case '+': // Simple string
        return { complete: true, value: data.substring(1, endIdx) };
      case '-': // Error
        return { complete: true, error: true, value: data.substring(1, endIdx) };
      case ':': // Integer
        return { complete: true, value: parseInt(data.substring(1, endIdx), 10) };
      case '$': // Bulk string
        const len = parseInt(data.substring(1, endIdx), 10);
        if (len === -1) return { complete: true, value: null };
        const valueStart = endIdx + 2;
        const valueEnd = valueStart + len;
        if (data.length < valueEnd + 2) return { complete: false };
        return { complete: true, value: data.substring(valueStart, valueEnd) };
      case '*': // Array
        return { complete: true, value: 'OK' }; // Simplified for our use case
      default:
        return { complete: true, value: data };
    }
  }

  async auth(password) {
    return this.sendCommand(['AUTH', password]);
  }

  async set(key, value) {
    const jsonValue = JSON.stringify(value);
    return this.sendCommand(['SET', key, jsonValue]);
  }

  async get(key) {
    const result = await this.sendCommand(['GET', key]);
    return result ? JSON.parse(result) : null;
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

/**
 * Register a single user in Redis
 */
async function registerUser(redis, userName, password, authMode) {
  const userKey = `user:${userName}`;

  // Check if user already exists
  const existing = await redis.exists(userKey);
  if (existing) {
    return { status: 'exists' };
  }

  // Prepare user data based on auth mode
  let userData;
  if (authMode === 'none') {
    // Store plain password
    userData = { password };
  } else if (authMode === 'service-integrated-manual') {
    // Store bcrypt hashed password
    const passwordHash = await Bcrypt.hash(password, BCRYPT_ROUNDS);
    userData = {
      userName,
      passwordHash,
      createdAt: new Date().toISOString()
    };
  }

  await redis.set(userKey, userData);
  return { status: 'registered' };
}

async function main() {
  const config = parseArgs();

  console.log('='.repeat(60));
  console.log('  Pre-registering Users in Redis');
  console.log('='.repeat(60));
  console.log(`\nAuth mode: ${config.auth}`);

  // Parse users
  console.log('\nReading users from users.csv...');
  const users = parseUsersCSV(config.limit);
  console.log(`Found ${users.length} users to register`);

  // Get Redis endpoint
  console.log('\nGetting Redis endpoint from Terraform...');
  const redisUrl = getRedisEndpoint();
  const redisConfig = parseRedisUrl(redisUrl);
  console.log(`Redis host: ${redisConfig.host}:${redisConfig.port}`);

  // Connect to Redis
  console.log('\nConnecting to Redis...');
  const redis = new RedisClient(redisConfig.host, redisConfig.port, redisConfig.password);
  await redis.connect();
  console.log('Connected to Redis');

  // Register users
  console.log(`\nRegistering users (${config.auth} mode)...`);
  let registered = 0;
  let alreadyExists = 0;
  let failed = 0;

  for (let i = 0; i < users.length; i++) {
    const user = users[i];
    try {
      const result = await registerUser(redis, user.userName, user.password, config.auth);
      if (result.status === 'registered') {
        registered++;
      } else if (result.status === 'exists') {
        alreadyExists++;
      }
    } catch (error) {
      failed++;
      console.error(`Failed to register ${user.userName}: ${error.message}`);
    }

    // Progress update
    if ((i + 1) % 100 === 0 || i === users.length - 1) {
      process.stdout.write(`\rProgress: ${i + 1}/${users.length} (${Math.round((i + 1) / users.length * 100)}%)`);
    }
  }

  console.log('\n');

  // Close Redis connection
  redis.close();

  // Summary
  console.log('Results:');
  console.log(`  Registered: ${registered}`);
  console.log(`  Already existed: ${alreadyExists}`);
  console.log(`  Failed: ${failed}`);

  console.log('\n' + '='.repeat(60));
  console.log('  Pre-registration Complete');
  console.log('='.repeat(60));

  if (failed > 0) {
    process.exit(1);
  }
}

main().catch(error => {
  console.error('Error:', error.message);
  process.exit(1);
});