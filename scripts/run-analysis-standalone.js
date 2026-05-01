#!/usr/bin/env node
/**
 * Standalone script to run remaining analysis steps for an existing experiment.
 * Generates insights.json (from existing dump.json) and log-analysis.json.
 * Usage: node scripts/run-analysis-standalone.js <outputDir>
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { analyzeExperimentLogs } = require('./experiment/log-analyzer');

const outputDir = process.argv[2];
if (!outputDir) {
  console.error('Usage: node scripts/run-analysis-standalone.js <outputDir>');
  process.exit(1);
}

const absoluteOutputDir = path.resolve(outputDir);
const analysisDir = path.join(absoluteOutputDir, 'analysis');
const dumpFile = path.join(analysisDir, 'dump.json');
const projectRoot = path.join(__dirname, '..');

async function main() {
  // Step 1: Generate insights.json from existing dump.json
  if (fs.existsSync(dumpFile)) {
    const stat = fs.statSync(dumpFile);
    console.log(`\nFound dump.json (${(stat.size / 1024 / 1024 / 1024).toFixed(1)} GB)`);

    const generateInsightsScript = path.join(projectRoot, 'scripts', 'generate_insights.py');
    if (fs.existsSync(generateInsightsScript)) {
      console.log('Generating insights.json...');
      try {
        execSync(`python3 "${generateInsightsScript}" "${dumpFile}" "${analysisDir}"`, {
          stdio: 'inherit',
          timeout: 600000 // 10 min
        });
        console.log('✓ insights.json generated successfully');
      } catch (error) {
        console.error('Insights generation failed:', error.message);
      }
    } else {
      console.log('generate_insights.py not found, skipping');
    }
  } else {
    console.log('No dump.json found, skipping insights generation');
  }

  // Step 2: Generate log-analysis.json
  console.log('\nAnalyzing logs for auth & Lambda metrics...');
  try {
    const logAnalysis = await analyzeExperimentLogs(absoluteOutputDir);
    if (logAnalysis) {
      if (logAnalysis.auth_metrics) {
        console.log('  ✓ Auth metrics analysis complete');
      }
      if (logAnalysis.lambda_metrics) {
        console.log('  ✓ Lambda metrics analysis complete');
      }
    }
    console.log('✓ log-analysis.json generated successfully');
  } catch (logError) {
    console.error('Log analysis failed:', logError.message);
  }

  // Summary
  console.log('\n========================================');
  console.log('Analysis complete. Files in', analysisDir + ':');
  for (const f of fs.readdirSync(analysisDir)) {
    const s = fs.statSync(path.join(analysisDir, f));
    console.log(`  ${f}: ${(s.size / 1024 / 1024).toFixed(1)} MB`);
  }
  console.log('========================================');
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});