#!/usr/bin/env node

/**
 * Extract Auth Overhead Per Endpoint from Artillery Logs
 *
 * This script parses artillery.log files and calculates auth overhead
 * by comparing authenticated vs anonymous requests within the same experiment.
 *
 * Similar to SQL Query 3.4 (Auth type overhead per endpoint)
 */

const fs = require('fs');
const path = require('path');
const readline = require('readline');

const resultsDir = process.argv[2] || path.join(__dirname, 'results/webservice');

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

async function extractLatenciesFromLog(logPath) {
  const beforeEvents = new Map(); // xPair -> event
  const latencies = []; // {endpoint, authType, latencyMs, statusCode, phase}

  return new Promise((resolve, reject) => {
    if (!fs.existsSync(logPath)) {
      resolve({ latencies, count: 0 });
      return;
    }

    const rl = readline.createInterface({
      input: fs.createReadStream(logPath, { encoding: 'utf8' }),
      crlfDelay: Infinity
    });

    rl.on('line', (line) => {
      const befaasMatch = line.match(/BEFAAS(\{.*\})$/);
      if (!befaasMatch) return;

      let data;
      try {
        data = JSON.parse(befaasMatch[1]);
      } catch (e) {
        return;
      }

      // Only process artillery events (client-side timing)
      if (data.fn?.name !== 'artillery') return;

      const event = data.event;
      if (!event?.xPair) return;

      if (event.type === 'before') {
        beforeEvents.set(event.xPair, {
          now: data.now,
          url: event.url,
          authType: event.authType,
          phase: data.phase
        });
      } else if (event.type === 'after') {
        const before = beforeEvents.get(event.xPair);
        if (before) {
          // Extract endpoint from URL
          const urlMatch = before.url?.match(/\.amazonaws\.com(\/[^?]+)/);
          const endpoint = urlMatch ? urlMatch[1] : before.url;

          latencies.push({
            endpoint,
            authType: before.authType,
            latencyMs: data.now - before.now,
            statusCode: event.statusCode,
            phase: before.phase?.name || 'unknown'
          });

          beforeEvents.delete(event.xPair);
        }
      }
    });

    rl.on('close', () => {
      resolve({ latencies, count: latencies.length });
    });

    rl.on('error', reject);
  });
}

function calculateStats(values) {
  if (!values || values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const sum = sorted.reduce((a, b) => a + b, 0);
  return {
    count: sorted.length,
    mean: sum / sorted.length,
    median: sorted[Math.floor(sorted.length / 2)],
    p75: sorted[Math.floor(sorted.length * 0.75)],
    p90: sorted[Math.floor(sorted.length * 0.90)],
    p95: sorted[Math.floor(sorted.length * 0.95)],
    p99: sorted[Math.floor(sorted.length * 0.99)],
    min: sorted[0],
    max: sorted[sorted.length - 1]
  };
}

async function analyzeRun(runDir) {
  const config = parseRunConfig(runDir);
  if (!config) return null;

  const logPath = path.join(runDir, 'logs', 'artillery.log');
  const { latencies } = await extractLatenciesFromLog(logPath);

  if (latencies.length === 0) return null;

  // Group by endpoint and authType
  const groups = {};
  for (const l of latencies) {
    if (l.statusCode !== 200) continue; // Only successful requests

    const key = `${l.endpoint}|${l.authType}`;
    if (!groups[key]) {
      groups[key] = { endpoint: l.endpoint, authType: l.authType, latencies: [] };
    }
    groups[key].latencies.push(l.latencyMs);
  }

  // Calculate stats for each group
  const stats = {};
  for (const [key, group] of Object.entries(groups)) {
    stats[key] = {
      endpoint: group.endpoint,
      authType: group.authType,
      ...calculateStats(group.latencies)
    };
  }

  return { config, stats, totalRequests: latencies.length };
}

function printOverheadTable(stats) {
  // Group endpoints
  const endpoints = [...new Set(Object.values(stats).map(s => s.endpoint))].sort();

  console.log('\nAuth Overhead Per Endpoint (auth vs anonymous, status=200):');
  console.log('-'.repeat(110));
  console.log(
    'Endpoint'.padEnd(35),
    'Auth Mean'.padStart(10),
    'Anon Mean'.padStart(10),
    'Overhead'.padStart(10),
    '%'.padStart(8),
    'Auth P99'.padStart(10),
    'Anon P99'.padStart(10),
    'P99 Ovhd'.padStart(10)
  );
  console.log('-'.repeat(110));

  const overheads = [];

  for (const endpoint of endpoints) {
    const authKey = `${endpoint}|auth`;
    const anonKey = `${endpoint}|anonymous`;

    const authStats = stats[authKey];
    const anonStats = stats[anonKey];

    if (!authStats || !anonStats) continue;

    const meanOverhead = authStats.mean - anonStats.mean;
    const meanOverheadPct = (meanOverhead / anonStats.mean) * 100;
    const p99Overhead = authStats.p99 - anonStats.p99;

    overheads.push({ endpoint, meanOverhead, meanOverheadPct, p99Overhead, authStats, anonStats });

    console.log(
      endpoint.padEnd(35),
      `${authStats.mean.toFixed(1)}ms`.padStart(10),
      `${anonStats.mean.toFixed(1)}ms`.padStart(10),
      `${meanOverhead >= 0 ? '+' : ''}${meanOverhead.toFixed(1)}ms`.padStart(10),
      `${meanOverheadPct >= 0 ? '+' : ''}${meanOverheadPct.toFixed(1)}%`.padStart(8),
      `${authStats.p99.toFixed(1)}ms`.padStart(10),
      `${anonStats.p99.toFixed(1)}ms`.padStart(10),
      `${p99Overhead >= 0 ? '+' : ''}${p99Overhead.toFixed(1)}ms`.padStart(10)
    );
  }

  if (overheads.length > 0) {
    // Summary
    const avgMeanOverhead = overheads.reduce((s, o) => s + o.meanOverhead, 0) / overheads.length;
    const avgMeanOverheadPct = overheads.reduce((s, o) => s + o.meanOverheadPct, 0) / overheads.length;
    const avgP99Overhead = overheads.reduce((s, o) => s + o.p99Overhead, 0) / overheads.length;

    console.log('-'.repeat(110));
    console.log(
      'AVERAGE'.padEnd(35),
      ''.padStart(10),
      ''.padStart(10),
      `${avgMeanOverhead >= 0 ? '+' : ''}${avgMeanOverhead.toFixed(1)}ms`.padStart(10),
      `${avgMeanOverheadPct >= 0 ? '+' : ''}${avgMeanOverheadPct.toFixed(1)}%`.padStart(8),
      ''.padStart(10),
      ''.padStart(10),
      `${avgP99Overhead >= 0 ? '+' : ''}${avgP99Overhead.toFixed(1)}ms`.padStart(10)
    );
  }

  return overheads;
}

function printPhaseBreakdown(runDir) {
  // This would require additional processing - skipping for now
}

async function main() {
  console.log('='.repeat(110));
  console.log('Auth Overhead Analysis from Local Logs');
  console.log('(Comparing authenticated vs anonymous requests within same experiment)');
  console.log('='.repeat(110));

  const entries = fs.readdirSync(resultsDir);

  for (const entry of entries.sort()) {
    const runDir = path.join(resultsDir, entry);
    if (!fs.statSync(runDir).isDirectory()) continue;

    const result = await analyzeRun(runDir);
    if (!result) continue;

    // Only show experiments with auth enabled
    if (result.config.auth === 'none') {
      console.log(`\n${result.config.dirname}: No auth (baseline) - ${result.totalRequests} requests`);
      continue;
    }

    console.log(`\n${'='.repeat(110)}`);
    console.log(`Experiment: ${result.config.dirname}`);
    console.log(`Auth Strategy: ${result.config.auth}, Memory: ${result.config.memory}MB`);
    console.log(`Total Requests: ${result.totalRequests}`);

    const overheads = printOverheadTable(result.stats);

    // Print detailed stats for authenticated requests
    console.log('\nDetailed Auth Request Stats:');
    console.log('-'.repeat(90));
    console.log(
      'Endpoint'.padEnd(35),
      'Count'.padStart(8),
      'Mean'.padStart(10),
      'Median'.padStart(10),
      'P95'.padStart(10),
      'P99'.padStart(10),
      'Max'.padStart(10)
    );
    console.log('-'.repeat(90));

    for (const o of overheads.sort((a, b) => b.meanOverhead - a.meanOverhead)) {
      const s = o.authStats;
      console.log(
        o.endpoint.padEnd(35),
        s.count.toString().padStart(8),
        `${s.mean.toFixed(1)}ms`.padStart(10),
        `${s.median.toFixed(1)}ms`.padStart(10),
        `${s.p95.toFixed(1)}ms`.padStart(10),
        `${s.p99.toFixed(1)}ms`.padStart(10),
        `${s.max.toFixed(1)}ms`.padStart(10)
      );
    }
  }

  console.log('\n' + '='.repeat(110));
  console.log('Note: This shows client-side auth overhead (total request time difference).');
  console.log('For server-side JWT verification timing per Lambda, re-run experiments with');
  console.log('BEFAAS filter enabled in lambda-logs.js (already updated).');
  console.log('='.repeat(110));
}

main().catch(console.error);