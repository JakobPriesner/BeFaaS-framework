const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { logSection } = require('./utils');

/**
 * Sanitize log files by removing malformed JSON entries
 * This prevents the befaas/analysis container from crashing on truncated logs
 * @param {string} logsDir - Directory containing log files
 * @returns {number} - Number of malformed entries removed
 */
function sanitizeLogs(logsDir) {
  let totalRemoved = 0;
  const logFiles = fs.readdirSync(logsDir).filter(f => f.endsWith('.log') || f.endsWith('.json'));

  for (const file of logFiles) {
    const filePath = path.join(logsDir, file);
    const stat = fs.statSync(filePath);
    if (!stat.isFile()) continue;

    const content = fs.readFileSync(filePath, 'utf8');
    const lines = content.split('\n');
    const validLines = [];
    let removed = 0;

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        validLines.push(line);
        continue;
      }

      // Check if line contains BEFAAS JSON entry (may be prefixed with ANSI codes/terraform output)
      const jsonMatch = trimmed.match(/BEFAAS(\{.*)$/);
      if (jsonMatch) {
        const jsonPart = jsonMatch[1];
        try {
          JSON.parse(jsonPart);
          validLines.push(line);
        } catch (e) {
          // Malformed JSON - skip this line
          removed++;
        }
      } else {
        // Non-JSON line, keep it
        validLines.push(line);
      }
    }

    if (removed > 0) {
      fs.writeFileSync(filePath, validLines.join('\n'));
      totalRemoved += removed;
    }
  }

  return totalRemoved;
}

async function analyzeResults(experiment, outputDir) {
  logSection('Analyzing Results');

  console.log(`Analyzing results in ${outputDir}...`);

  const logsDir = path.join(outputDir, 'logs');
  if (!fs.existsSync(logsDir)) {
    console.log('No logs directory found, skipping analysis');
    return;
  }

  const analysisDir = path.join(outputDir, 'analysis');
  if (!fs.existsSync(analysisDir)) {
    fs.mkdirSync(analysisDir, { recursive: true });
  }

  const projectRoot = path.join(__dirname, '..', '..');
  const absoluteLogsDir = path.resolve(logsDir);
  const absoluteAnalysisDir = path.resolve(analysisDir);

  try {
    // Step 0: Sanitize logs by removing malformed JSON entries
    console.log('\nStep 0: Sanitizing logs (removing malformed entries)...');
    const removedCount = sanitizeLogs(absoluteLogsDir);
    if (removedCount > 0) {
      console.log(`  Removed ${removedCount} malformed log entries`);
    } else {
      console.log('  All log entries are valid');
    }

    // Step 1: Generate dump.json using befaas/analysis container
    console.log('\nStep 1: Generating dump.json from logs...');
    const containerLogsDir = `/experiments/${path.relative(projectRoot, absoluteLogsDir)}`;
    const containerAnalysisDir = `/experiments/${path.relative(projectRoot, absoluteAnalysisDir)}`;

    execSync(`docker run --rm -v "${projectRoot}":/experiments befaas/analysis "${containerLogsDir}" "${containerAnalysisDir}"`, {
      stdio: 'inherit',
      shell: '/bin/bash'
    });

    const dumpFile = path.join(analysisDir, 'dump.json');
    if (!fs.existsSync(dumpFile)) {
      console.log('dump.json not created, skipping further analysis');
      return;
    }

    console.log('dump.json generated successfully');

    // Step 2: Generate insights.json with comprehensive metrics
    console.log('\nStep 2: Generating insights.json...');
    const generateInsightsScript = path.join(projectRoot, 'scripts', 'generate_insights.py');
    const requirementsFile = path.join(projectRoot, 'scripts', 'requirements.txt');

    if (fs.existsSync(generateInsightsScript)) {
      try {
        // Check if required Python packages are installed
        try {
          execSync('python3 -c "import numpy"', { stdio: 'pipe' });
        } catch (importError) {
          console.log('Installing Python dependencies...');
          if (fs.existsSync(requirementsFile)) {
            execSync(`pip3 install -r "${requirementsFile}"`, { stdio: 'inherit' });
          } else {
            execSync('pip3 install numpy', { stdio: 'inherit' });
          }
        }

        execSync(`python3 "${generateInsightsScript}" "${dumpFile}" "${analysisDir}"`, {
          stdio: 'inherit'
        });
        console.log('insights.json generated successfully');
      } catch (error) {
        console.error('Insights generation failed:', error.message);
        console.log('   Try: pip3 install numpy');
      }
    } else {
      console.log('generate_insights.py not found, skipping insights generation');
    }

    console.log('\nAnalysis completed successfully');
    console.log(`\nAnalysis results saved to: ${analysisDir}`);
    console.log('  - dump.json: Raw performance data from logs');
    console.log('  - insights.json: Comprehensive performance metrics');
    console.log('    - HTTP status distribution and response times');
    console.log('    - Per-endpoint metrics (request count, response times, auth times)');
    console.log('    - Per-function metrics (request count, response times, auth times)');
    console.log('    - Throughput timeline (requests/auth ops per minute)');
    console.log('    - Correlations (load vs latency, load vs errors)');
    console.log('    - Call chain breakdowns (time spent in each function)');
    console.log('    - Auth chain breakdowns (auth time per function in chain)');

  } catch (error) {
    console.error('Analysis failed:', error.message);
    console.log('Note: Analysis requires Docker and the befaas/analysis image');
    // Don't throw - analysis is optional
  }
}

module.exports = {
  analyzeResults
};