#!/usr/bin/env node

/**
 * Auth Overhead Analysis Script
 *
 * Calculates authentication overhead per endpoint by comparing
 * auth-enabled runs vs no-auth runs.
 *
 * Usage: node scripts/auth-overhead-analysis.js <results-dir>
 *
 * NOTE: Per-function auth timing requires BEFAAS logs in CloudWatch.
 *       The current CloudWatch filter only collects REPORT entries.
 *       To get per-function auth timing, update lambda-logs.js to include 'BEFAAS' in LOG_FILTER_PATTERNS
 */

const fs = require('fs');
const path = require('path');

const resultsDir = process.argv[2] || path.join(__dirname, 'results/webservice');

// Map endpoints to underlying Lambda functions
const ENDPOINT_TO_FUNCTIONS = {
  '/frontend': ['frontend'],
  '/frontend/product/EASYSTOOL': ['frontend', 'getproduct', 'listproducts', 'listrecommendations', 'currency', 'getads'],
  '/frontend/product/QWERTY': ['frontend', 'getproduct', 'listproducts', 'listrecommendations', 'currency', 'getads'],
  '/frontend/product/REFLECTXXX': ['frontend', 'getproduct', 'listproducts', 'listrecommendations', 'currency', 'getads'],
  '/frontend/addCartItem': ['frontend', 'addcartitem', 'getcart', 'cartkvstorage'],
  '/frontend/cart': ['frontend', 'getcart', 'cartkvstorage', 'currency'],
  '/frontend/checkout': ['frontend', 'checkout', 'getcart', 'cartkvstorage', 'payment', 'shipmentquote', 'shiporder', 'email', 'emptycart', 'currency'],
  '/frontend/setUser': ['frontend', 'login', 'register']
};

function loadInsights(runDir) {
  const insightsPath = path.join(runDir, 'analysis', 'insights.json');
  if (!fs.existsSync(insightsPath)) {
    return null;
  }
  try {
    return JSON.parse(fs.readFileSync(insightsPath, 'utf8'));
  } catch (err) {
    console.warn(`Warning: Could not parse ${insightsPath}: ${err.message}`);
    return null;
  }
}

function parseRunConfig(runDir) {
  const dirname = path.basename(runDir);
  // Format: faas_<auth>_<memory>_<workload>_<timestamp>
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

function analyzeAuthOverhead() {
  console.log('Auth Overhead Analysis');
  console.log('='.repeat(60));
  console.log();

  // Find all experiment runs
  const runs = [];
  for (const entry of fs.readdirSync(resultsDir)) {
    const runDir = path.join(resultsDir, entry);
    if (!fs.statSync(runDir).isDirectory()) continue;

    const config = parseRunConfig(runDir);
    if (!config) continue;

    const insights = loadInsights(runDir);
    if (!insights) continue;

    runs.push({ ...config, runDir, insights });
  }

  // Group by memory size
  const byMemory = {};
  for (const run of runs) {
    const key = run.memory;
    if (!byMemory[key]) byMemory[key] = [];
    byMemory[key].push(run);
  }

  // Calculate overhead for each memory size
  for (const [memory, memoryRuns] of Object.entries(byMemory).sort((a, b) => a[0] - b[0])) {
    const noAuth = memoryRuns.find(r => r.auth === 'none');
    const authRuns = memoryRuns.filter(r => r.auth !== 'none');

    if (!noAuth) {
      console.log(`${memory}MB: No baseline (no-auth) run found`);
      continue;
    }

    console.log(`\n${'='.repeat(60)}`);
    console.log(`Memory: ${memory}MB`);
    console.log(`${'='.repeat(60)}`);
    console.log(`Baseline (no-auth): ${noAuth.dirname}`);

    for (const authRun of authRuns) {
      console.log(`\n--- Auth Strategy: ${authRun.auth} ---`);
      console.log(`Run: ${authRun.dirname}`);
      console.log();

      console.log('Per-Endpoint Auth Overhead (auth - no-auth):');
      console.log('-'.repeat(80));
      console.log(
        'Endpoint'.padEnd(35),
        'Mean'.padStart(10),
        'Median'.padStart(10),
        'P95'.padStart(10),
        'P99'.padStart(10)
      );
      console.log('-'.repeat(80));

      const baseEndpoints = noAuth.insights.endpoints.response_times;
      const authEndpoints = authRun.insights.endpoints.response_times;

      const overheads = [];
      for (const [endpoint, baseTime] of Object.entries(baseEndpoints)) {
        const authTime = authEndpoints[endpoint];
        if (!authTime) continue;

        const overhead = {
          endpoint,
          mean: authTime.mean_ms - baseTime.mean_ms,
          median: authTime.median_ms - baseTime.median_ms,
          p95: authTime.p95_ms - baseTime.p95_ms,
          p99: authTime.p99_ms - baseTime.p99_ms,
          functions: ENDPOINT_TO_FUNCTIONS[endpoint] || ['unknown']
        };
        overheads.push(overhead);

        console.log(
          endpoint.padEnd(35),
          `${overhead.mean >= 0 ? '+' : ''}${overhead.mean.toFixed(1)}ms`.padStart(10),
          `${overhead.median >= 0 ? '+' : ''}${overhead.median.toFixed(1)}ms`.padStart(10),
          `${overhead.p95 >= 0 ? '+' : ''}${overhead.p95.toFixed(1)}ms`.padStart(10),
          `${overhead.p99 >= 0 ? '+' : ''}${overhead.p99.toFixed(1)}ms`.padStart(10)
        );
      }

      // Summary
      const avgMeanOverhead = overheads.reduce((s, o) => s + o.mean, 0) / overheads.length;
      const avgMedianOverhead = overheads.reduce((s, o) => s + o.median, 0) / overheads.length;
      console.log('-'.repeat(80));
      console.log(
        'AVERAGE'.padEnd(35),
        `${avgMeanOverhead >= 0 ? '+' : ''}${avgMeanOverhead.toFixed(1)}ms`.padStart(10),
        `${avgMedianOverhead >= 0 ? '+' : ''}${avgMedianOverhead.toFixed(1)}ms`.padStart(10)
      );

      // Functions involved per endpoint
      console.log('\nFunctions invoked per endpoint:');
      for (const o of overheads) {
        console.log(`  ${o.endpoint}: ${o.functions.join(' → ')}`);
      }
    }
  }

  // Print note about per-function data
  console.log('\n' + '='.repeat(60));
  console.log('NOTE: Per-Function Auth Timing');
  console.log('='.repeat(60));
  console.log(`
The above shows per-ENDPOINT overhead (total request time difference).
For per-FUNCTION auth timing (how long JWT verification takes in each Lambda),
you need to:

1. Update scripts/experiment/lambda-logs.js, line 19:
   Add 'BEFAAS' to LOG_FILTER_PATTERNS:

   const LOG_FILTER_PATTERNS = [
     'REPORT RequestId',
     'ERROR',
     'BEFAAS'  // <-- ADD THIS
   ];

2. Re-run the experiment to collect the auth timing logs

3. The BEFAAS entries will contain:
   {"fn":{"name":"frontend"},"event":{"authCheck":{"durationMs":12.5,"success":true}}}

   This gives you the exact JWT verification time per function.
`);
}

analyzeAuthOverhead();