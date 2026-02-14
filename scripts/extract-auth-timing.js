#!/usr/bin/env node

/**
 * Extract Per-Function Auth Timing from BEFAAS CloudWatch Logs
 *
 * Usage: node scripts/extract-auth-timing.js <results-dir>
 *
 * This script extracts auth timing data from the aws.log files that contain
 * BEFAAS entries with authCheck timing data.
 *
 * Example BEFAAS auth entry:
 * BEFAAS{"timestamp":1234567890,"fn":{"name":"frontend"},"event":{"contextId":"abc123","authCheck":{"durationMs":12.5,"success":true}}}
 */

const fs = require('fs');
const path = require('path');
const readline = require('readline');

const resultsDir = process.argv[2] || path.join(__dirname, 'results/webservice');

async function extractAuthTimingFromFile(awsLogPath) {
  const authTiming = {};  // fnName -> array of durations
  let totalEntries = 0;
  let authEntries = 0;

  return new Promise((resolve, reject) => {
    if (!fs.existsSync(awsLogPath)) {
      resolve({ authTiming, totalEntries, authEntries });
      return;
    }

    const rl = readline.createInterface({
      input: fs.createReadStream(awsLogPath, { encoding: 'utf8' }),
      crlfDelay: Infinity
    });

    rl.on('line', (line) => {
      totalEntries++;

      // Parse JSON line
      let entry;
      try {
        entry = JSON.parse(line);
      } catch (e) {
        return;
      }

      // Check if message contains BEFAAS with authCheck
      const message = entry.message || '';
      const befaasMatch = message.match(/BEFAAS(\{.*\})$/);
      if (!befaasMatch) return;

      let befaasData;
      try {
        befaasData = JSON.parse(befaasMatch[1]);
      } catch (e) {
        return;
      }

      // Extract auth timing
      if (befaasData.event?.authCheck?.durationMs !== undefined) {
        const fnName = befaasData.fn?.name || 'unknown';
        const duration = befaasData.event.authCheck.durationMs;
        const success = befaasData.event.authCheck.success;

        if (!authTiming[fnName]) {
          authTiming[fnName] = { success: [], failed: [] };
        }

        if (success) {
          authTiming[fnName].success.push(duration);
        } else {
          authTiming[fnName].failed.push(duration);
        }

        authEntries++;
      }
    });

    rl.on('close', () => {
      resolve({ authTiming, totalEntries, authEntries });
    });

    rl.on('error', (err) => {
      reject(err);
    });
  });
}

function calculateStats(durations) {
  if (durations.length === 0) return null;

  const sorted = [...durations].sort((a, b) => a - b);
  const sum = sorted.reduce((a, b) => a + b, 0);

  return {
    count: sorted.length,
    mean: sum / sorted.length,
    median: sorted[Math.floor(sorted.length / 2)],
    min: sorted[0],
    max: sorted[sorted.length - 1],
    p75: sorted[Math.floor(sorted.length * 0.75)],
    p90: sorted[Math.floor(sorted.length * 0.90)],
    p95: sorted[Math.floor(sorted.length * 0.95)],
    p99: sorted[Math.floor(sorted.length * 0.99)]
  };
}

function parseRunConfig(runDir) {
  const dirname = path.basename(runDir);
  const match = dirname.match(/^faas_([^_]+)_(\d+)MB_([^_]+)_(.+)$/);
  if (!match) return null;
  return {
    auth: match[1],
    memory: parseInt(match[2]),
    workload: match[3],
    timestamp: match[4],
    dirname
  };
}

async function analyzeRun(runDir) {
  const config = parseRunConfig(runDir);
  if (!config) return null;

  const awsLogPath = path.join(runDir, 'logs', 'aws.log');
  const { authTiming, totalEntries, authEntries } = await extractAuthTimingFromFile(awsLogPath);

  if (authEntries === 0) {
    return { config, hasAuthTiming: false };
  }

  // Calculate stats for each function
  const stats = {};
  for (const [fnName, data] of Object.entries(authTiming)) {
    stats[fnName] = {
      success: calculateStats(data.success),
      failed: calculateStats(data.failed)
    };
  }

  return {
    config,
    hasAuthTiming: true,
    totalEntries,
    authEntries,
    stats
  };
}

async function main() {
  console.log('Per-Function Auth Timing Analysis');
  console.log('='.repeat(60));
  console.log();

  // Find all experiment runs
  const entries = fs.readdirSync(resultsDir);
  let hasAnyAuthTiming = false;

  for (const entry of entries) {
    const runDir = path.join(resultsDir, entry);
    if (!fs.statSync(runDir).isDirectory()) continue;

    const result = await analyzeRun(runDir);
    if (!result) continue;

    if (!result.hasAuthTiming) {
      console.log(`${result.config.dirname}: No BEFAAS auth timing data found`);
      continue;
    }

    hasAnyAuthTiming = true;

    console.log();
    console.log('='.repeat(80));
    console.log(`Run: ${result.config.dirname}`);
    console.log(`Auth: ${result.config.auth}, Memory: ${result.config.memory}MB`);
    console.log(`Total log entries: ${result.totalEntries}, Auth entries: ${result.authEntries}`);
    console.log('='.repeat(80));
    console.log();

    // Print per-function stats
    console.log('Per-Function Auth Timing (successful auth checks):');
    console.log('-'.repeat(90));
    console.log(
      'Function'.padEnd(25),
      'Count'.padStart(8),
      'Mean'.padStart(10),
      'Median'.padStart(10),
      'P95'.padStart(10),
      'P99'.padStart(10),
      'Max'.padStart(10)
    );
    console.log('-'.repeat(90));

    for (const [fnName, data] of Object.entries(result.stats).sort((a, b) => a[0].localeCompare(b[0]))) {
      const s = data.success;
      if (!s) continue;

      console.log(
        fnName.padEnd(25),
        s.count.toString().padStart(8),
        `${s.mean.toFixed(2)}ms`.padStart(10),
        `${s.median.toFixed(2)}ms`.padStart(10),
        `${s.p95.toFixed(2)}ms`.padStart(10),
        `${s.p99.toFixed(2)}ms`.padStart(10),
        `${s.max.toFixed(2)}ms`.padStart(10)
      );
    }

    // Check for failed auth
    const failedCounts = Object.entries(result.stats)
      .filter(([_, d]) => d.failed && d.failed.count > 0)
      .map(([fn, d]) => `${fn}: ${d.failed.count}`)
      .join(', ');

    if (failedCounts) {
      console.log();
      console.log(`Failed auth checks: ${failedCounts}`);
    }
  }

  if (!hasAnyAuthTiming) {
    console.log();
    console.log('No BEFAAS auth timing data found in any experiment run.');
    console.log();
    console.log('To collect per-function auth timing:');
    console.log('1. Ensure lambda-logs.js includes "BEFAAS" in LOG_FILTER_PATTERNS');
    console.log('2. Re-run experiments with auth enabled (service-integrated or service-integrated-manual)');
    console.log('3. The aws.log will then contain BEFAAS entries with authCheck timing');
  }
}

main().catch(console.error);