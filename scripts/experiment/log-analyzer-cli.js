#!/usr/bin/env node
// Thin CLI wrapper around analyzeExperimentLogs, used by scripts/reanalyze-s3-runs.sh
// to regenerate analysis/log-analysis.json for a single run directory without
// running the full (Docker + Python) analysis pipeline.

const path = require('path');
const { analyzeExperimentLogs } = require('./log-analyzer');

const runDir = process.argv[2];
if (!runDir) {
  console.error('Usage: node scripts/experiment/log-analyzer-cli.js <runDir>');
  process.exit(1);
}

analyzeExperimentLogs(path.resolve(runDir))
  .then(() => process.exit(0))
  .catch((err) => {
    console.error('log-analyzer failed:', err && err.stack ? err.stack : err);
    process.exit(1);
  });