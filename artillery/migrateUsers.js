#!/usr/bin/env node

/**
 * Migrate existing users.csv to include precomputed bcrypt password hashes.
 *
 * This script reads an existing users.csv (with userName,password columns)
 * and outputs a new CSV with an additional passwordHash column.
 *
 * Usage:
 *   node migrateUsers.js [options]
 *
 * Options:
 *   --input, -i     Input CSV file (default: users.csv)
 *   --output, -o    Output CSV file (default: users-migrated.csv)
 *   --rounds, -r    Bcrypt rounds (default: 10)
 *   --force, -f     Overwrite output file if it exists
 *   --help, -h      Show help
 *
 * IMPORTANT: This script will NOT overwrite the input file.
 * Use --output to specify a different output file name.
 */

const fs = require('fs');
const path = require('path');

// Parse command line arguments
function parseArgs() {
  const args = process.argv.slice(2);
  const config = {
    input: 'users.csv',
    output: 'users-migrated.csv',
    rounds: 10,
    force: false
  };

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--input':
      case '-i':
        config.input = args[++i];
        break;
      case '--output':
      case '-o':
        config.output = args[++i];
        break;
      case '--rounds':
      case '-r':
        config.rounds = parseInt(args[++i], 10);
        break;
      case '--force':
      case '-f':
        config.force = true;
        break;
      case '--help':
      case '-h':
        printUsage();
        process.exit(0);
    }
  }

  return config;
}

function printUsage() {
  console.log(`
Usage: node migrateUsers.js [options]

Migrate existing users.csv to include precomputed bcrypt password hashes.

Options:
  --input, -i     Input CSV file (default: users.csv)
  --output, -o    Output CSV file (default: users-migrated.csv)
  --rounds, -r    Bcrypt rounds (default: 10)
  --force, -f     Overwrite output file if it exists
  --help, -h      Show help

Examples:
  node migrateUsers.js
  node migrateUsers.js --input old-users.csv --output new-users.csv
  node migrateUsers.js -i users.csv -o users-with-hashes.csv -r 12

IMPORTANT: This script will NOT overwrite the input file.
`);
}

/**
 * Parse CSV file and return array of user objects
 */
function parseCSV(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  const lines = content.trim().split('\n');
  const header = lines[0].split(',');

  const userNameIndex = header.indexOf('userName');
  const passwordIndex = header.indexOf('password');
  const passwordHashIndex = header.indexOf('passwordHash');

  if (userNameIndex === -1 || passwordIndex === -1) {
    throw new Error('CSV must have userName and password columns');
  }

  const users = [];
  for (let i = 1; i < lines.length; i++) {
    const fields = lines[i].split(',');
    if (fields.length > Math.max(userNameIndex, passwordIndex)) {
      const user = {
        userName: fields[userNameIndex],
        password: fields[passwordIndex]
      };

      // Preserve existing hash if present
      if (passwordHashIndex !== -1 && fields[passwordHashIndex]) {
        user.passwordHash = fields[passwordHashIndex];
      }

      users.push(user);
    }
  }

  return { users, hasExistingHashes: passwordHashIndex !== -1 };
}

/**
 * Hash passwords in batches with progress reporting
 */
async function hashPasswordsBatch(passwords, rounds, onProgress) {
  const bcrypt = require('bcryptjs');
  const hashes = [];
  const batchSize = 100;

  for (let i = 0; i < passwords.length; i += batchSize) {
    const batch = passwords.slice(i, i + batchSize);
    const batchHashes = await Promise.all(
      batch.map(pwd => new Promise((resolve, reject) => {
        bcrypt.hash(pwd, rounds, (err, hash) => {
          if (err) reject(err);
          else resolve(hash);
        });
      }))
    );
    hashes.push(...batchHashes);

    if (onProgress) {
      onProgress(Math.min(i + batchSize, passwords.length), passwords.length);
    }
  }

  return hashes;
}

async function migrateUsers(config) {
  console.log('='.repeat(60));
  console.log('  Migrating Users CSV with Bcrypt Hashes');
  console.log('='.repeat(60));
  console.log(`\nInput:  ${config.input}`);
  console.log(`Output: ${config.output}`);
  console.log(`Bcrypt rounds: ${config.rounds}`);

  // Safety check: don't overwrite input
  const inputPath = path.resolve(config.input);
  const outputPath = path.resolve(config.output);

  if (inputPath === outputPath) {
    console.error('\nError: Input and output files cannot be the same.');
    console.error('This script will NOT overwrite the original users.csv.');
    console.error('Please specify a different output file with --output.');
    process.exit(1);
  }

  // Check if input exists
  if (!fs.existsSync(config.input)) {
    console.error(`\nError: Input file not found: ${config.input}`);
    process.exit(1);
  }

  // Check if output exists
  if (fs.existsSync(config.output) && !config.force) {
    console.error(`\nError: Output file already exists: ${config.output}`);
    console.error('Use --force to overwrite.');
    process.exit(1);
  }

  // Parse input CSV
  console.log('\nReading input CSV...');
  const { users, hasExistingHashes } = parseCSV(config.input);
  console.log(`Found ${users.length} users`);

  if (hasExistingHashes) {
    console.log('Note: Input CSV already has passwordHash column');
  }

  // Find users that need hashing
  const usersNeedingHash = users.filter(u => !u.passwordHash);
  console.log(`Users needing hash computation: ${usersNeedingHash.length}`);

  if (usersNeedingHash.length > 0) {
    // Compute bcrypt hashes with progress
    console.log('\nComputing bcrypt hashes (this may take a while)...');
    const startTime = Date.now();

    const passwords = usersNeedingHash.map(u => u.password);
    const hashes = await hashPasswordsBatch(passwords, config.rounds, (current, total) => {
      const percent = Math.round(current / total * 100);
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      process.stdout.write(`\rProgress: ${current}/${total} (${percent}%) - ${elapsed}s`);
    });

    console.log('\n');

    // Assign hashes to users
    usersNeedingHash.forEach((user, i) => {
      user.passwordHash = hashes[i];
    });

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    console.log(`Hash computation completed in ${elapsed}s`);
  } else {
    console.log('\nAll users already have password hashes.');
  }

  // Write output CSV
  console.log('\nWriting output CSV...');
  const csvRows = ['userName,password,passwordHash'];
  users.forEach(user => {
    csvRows.push(`${user.userName},${user.password},${user.passwordHash}`);
  });

  fs.writeFileSync(config.output, csvRows.join('\n'));

  console.log(`\nMigration complete!`);
  console.log(`Output written to: ${config.output}`);
  console.log('='.repeat(60));

  // Print next steps
  console.log('\nNext steps:');
  console.log(`  1. Verify the output: head -5 ${config.output}`);
  console.log(`  2. If correct, replace the original:`);
  console.log(`     mv ${config.input} ${config.input}.backup`);
  console.log(`     mv ${config.output} ${config.input}`);
}

// Main
const config = parseArgs();

migrateUsers(config).catch(error => {
  console.error('Error:', error.message);
  process.exit(1);
});