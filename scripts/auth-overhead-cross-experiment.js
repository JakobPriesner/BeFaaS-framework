#!/usr/bin/env node

/**
 * Auth Overhead Analysis - Cross-Experiment Comparison
 *
 * Compares baseline (no-auth) experiments against auth-enabled experiments
 * to calculate the true auth overhead.
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
  const beforeEvents = new Map();
  const latencies = [];

  return new Promise((resolve, reject) => {
    if (!fs.existsSync(logPath)) {
      resolve({ latencies });
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
          const urlMatch = before.url?.match(/\.amazonaws\.com(\/[^?]+)/);
          const endpoint = urlMatch ? urlMatch[1] : before.url;

          latencies.push({
            endpoint,
            authType: before.authType,
            latencyMs: data.now - before.now,
            statusCode: event.statusCode,
            phase: before.phase?.name || 'unknown',
            phaseIndex: before.phase?.index ?? -1
          });
          beforeEvents.delete(event.xPair);
        }
      }
    });

    rl.on('close', () => resolve({ latencies }));
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

async function main() {
  console.log('='.repeat(110));
  console.log('Auth Overhead Analysis - Cross-Experiment Comparison');
  console.log('(Baseline no-auth vs Auth-enabled experiments)');
  console.log('='.repeat(110));

  const entries = fs.readdirSync(resultsDir);
  const experiments = {};

  // Load all experiments
  for (const entry of entries) {
    const runDir = path.join(resultsDir, entry);
    if (!fs.statSync(runDir).isDirectory()) continue;

    const config = parseRunConfig(runDir);
    if (!config) continue;

    const logPath = path.join(runDir, 'logs', 'artillery.log');
    const { latencies } = await extractLatenciesFromLog(logPath);

    if (latencies.length === 0) continue;

    // Group by endpoint (only successful requests)
    const byEndpoint = {};
    for (const l of latencies) {
      if (l.statusCode !== 200) continue;
      if (!byEndpoint[l.endpoint]) byEndpoint[l.endpoint] = [];
      byEndpoint[l.endpoint].push(l.latencyMs);
    }

    // Calculate stats per endpoint
    const stats = {};
    for (const [ep, lats] of Object.entries(byEndpoint)) {
      stats[ep] = calculateStats(lats);
    }

    experiments[config.dirname] = { config, stats, totalRequests: latencies.length };
  }

  // Group by memory size
  const byMemory = {};
  for (const [name, exp] of Object.entries(experiments)) {
    const mem = exp.config.memory;
    if (!byMemory[mem]) byMemory[mem] = {};
    byMemory[mem][name] = exp;
  }

  // Compare for each memory size
  for (const [memory, memExps] of Object.entries(byMemory).sort((a, b) => a[0] - b[0])) {
    console.log(`\n${'#'.repeat(110)}`);
    console.log(`# Memory: ${memory}MB`);
    console.log(`${'#'.repeat(110)}`);

    // Find baseline (no-auth)
    const baseline = Object.values(memExps).find(e => e.config.auth === 'none');
    const authExps = Object.values(memExps).filter(e => e.config.auth !== 'none');

    if (!baseline) {
      console.log('No baseline (no-auth) experiment found for this memory configuration');
      continue;
    }

    console.log(`\nBaseline: ${baseline.config.dirname} (${baseline.totalRequests} requests)`);

    for (const authExp of authExps) {
      console.log(`\n${'='.repeat(110)}`);
      console.log(`Auth Experiment: ${authExp.config.dirname}`);
      console.log(`Auth Strategy: ${authExp.config.auth}`);
      console.log(`Total Requests: ${authExp.totalRequests}`);
      console.log();

      console.log('Auth Overhead (auth experiment - baseline):');
      console.log('-'.repeat(110));
      console.log(
        'Endpoint'.padEnd(35),
        'Auth Mean'.padStart(10),
        'Base Mean'.padStart(10),
        'Overhead'.padStart(10),
        '%'.padStart(8),
        'Auth P99'.padStart(10),
        'Base P99'.padStart(10),
        'P99 Ovhd'.padStart(10)
      );
      console.log('-'.repeat(110));

      const overheads = [];
      const endpoints = [...new Set([...Object.keys(baseline.stats), ...Object.keys(authExp.stats)])].sort();

      for (const ep of endpoints) {
        const baseStats = baseline.stats[ep];
        const authStats = authExp.stats[ep];

        if (!baseStats || !authStats) continue;

        const meanOverhead = authStats.mean - baseStats.mean;
        const meanOverheadPct = (meanOverhead / baseStats.mean) * 100;
        const p99Overhead = authStats.p99 - baseStats.p99;

        overheads.push({ endpoint: ep, meanOverhead, meanOverheadPct, p99Overhead, authStats, baseStats });

        console.log(
          ep.padEnd(35),
          `${authStats.mean.toFixed(1)}ms`.padStart(10),
          `${baseStats.mean.toFixed(1)}ms`.padStart(10),
          `${meanOverhead >= 0 ? '+' : ''}${meanOverhead.toFixed(1)}ms`.padStart(10),
          `${meanOverheadPct >= 0 ? '+' : ''}${meanOverheadPct.toFixed(1)}%`.padStart(8),
          `${authStats.p99.toFixed(1)}ms`.padStart(10),
          `${baseStats.p99.toFixed(1)}ms`.padStart(10),
          `${p99Overhead >= 0 ? '+' : ''}${p99Overhead.toFixed(1)}ms`.padStart(10)
        );
      }

      if (overheads.length > 0) {
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

        // Show highest overhead endpoints
        console.log('\nHighest Auth Overhead Endpoints (sorted by overhead):');
        for (const o of overheads.sort((a, b) => b.meanOverhead - a.meanOverhead).slice(0, 5)) {
          console.log(`  ${o.endpoint}: +${o.meanOverhead.toFixed(1)}ms (${o.meanOverheadPct.toFixed(1)}%)`);
        }
      }
    }
  }

  console.log('\n' + '='.repeat(110));
  console.log('Summary: This compares total request latency between no-auth and auth-enabled experiments.');
  console.log('The overhead includes: JWT token transmission, Lambda-side JWT verification, and any');
  console.log('additional network latency from the auth flow.');
  console.log('='.repeat(110));
}

main().catch(console.error);