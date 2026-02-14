const fs = require('fs');
const path = require('path');
const readline = require('readline');
const { execSync } = require('child_process');
const { logSection } = require('./utils');
const { analyzeExperimentLogs } = require('./log-analyzer');

// Process a single line for sanitization
function processLine(line) {
  const trimmed = line.trim();
  if (!trimmed) {
    return { line, action: 'keep' };
  }

  // Check if line contains BEFAAS JSON entry (may be prefixed with ANSI codes/terraform output)
  const jsonMatch = trimmed.match(/BEFAAS(\{.*)$/);
  if (jsonMatch) {
    const jsonPart = jsonMatch[1];
    try {
      JSON.parse(jsonPart);

      // Pre-escape backslashes for the befaas library's unicode_escape decoding bug.
      // The befaas library uses .decode("unicode_escape") which converts \" to ",
      // breaking JSON strings with escaped quotes. By doubling backslashes, we
      // ensure they survive the unicode_escape decoding.
      let cleanJson = jsonPart;
      if (jsonPart.includes('\\"')) {
        cleanJson = jsonPart.replace(/\\"/g, '\\\\"');
      }

      // Extract clean BEFAAS line without terraform/ANSI prefixes
      // This is necessary for the befaas/analysis container to parse the logs
      const cleanLine = 'BEFAAS' + cleanJson;
      const wasModified = cleanLine !== line || jsonPart !== cleanJson;
      return { line: cleanLine, action: wasModified ? 'fixed' : 'keep' };
    } catch (e) {
      // Malformed JSON - skip this line
      return { line: null, action: 'removed' };
    }
  } else {
    // Non-JSON line, keep it
    return { line, action: 'keep' };
  }
}

// Stream-based sanitization for large files
async function sanitizeFileStreaming(filePath) {
  const tempPath = filePath + '.tmp';
  let removed = 0;
  let fixed = 0;
  let modified = false;

  return new Promise((resolve, reject) => {
    const readStream = fs.createReadStream(filePath, { encoding: 'utf8' });
    const writeStream = fs.createWriteStream(tempPath, { encoding: 'utf8' });
    const rl = readline.createInterface({
      input: readStream,
      crlfDelay: Infinity
    });

    let isFirst = true;

    rl.on('line', (line) => {
      const result = processLine(line);

      if (result.action === 'removed') {
        removed++;
        modified = true;
      } else {
        if (!isFirst) {
          writeStream.write('\n');
        }
        isFirst = false;
        writeStream.write(result.line);

        if (result.action === 'fixed') {
          fixed++;
          modified = true;
        }
      }
    });

    rl.on('close', () => {
      writeStream.end(() => {
        if (modified) {
          // Replace original with sanitized version
          fs.renameSync(tempPath, filePath);
        } else {
          // No changes needed, remove temp file
          fs.unlinkSync(tempPath);
        }
        resolve({ removed, fixed });
      });
    });

    rl.on('error', (err) => {
      writeStream.destroy();
      try { fs.unlinkSync(tempPath); } catch (e) {}
      reject(err);
    });

    readStream.on('error', (err) => {
      writeStream.destroy();
      try { fs.unlinkSync(tempPath); } catch (e) {}
      reject(err);
    });
  });
}

// Memory-based sanitization for small files
function sanitizeFileInMemory(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  const lines = content.split('\n');
  const validLines = [];
  let removed = 0;
  let fixed = 0;

  for (const line of lines) {
    const result = processLine(line);

    if (result.action === 'removed') {
      removed++;
    } else {
      validLines.push(result.line);
      if (result.action === 'fixed') {
        fixed++;
      }
    }
  }

  if (removed > 0 || fixed > 0) {
    fs.writeFileSync(filePath, validLines.join('\n'));
  }

  return { removed, fixed };
}

// Size threshold for streaming vs in-memory processing (100MB)
const STREAMING_THRESHOLD = 100 * 1024 * 1024;

async function sanitizeLogs(logsDir) {
  let totalRemoved = 0;
  let totalFixed = 0;
  const logFiles = fs.readdirSync(logsDir).filter(f => f.endsWith('.log') || f.endsWith('.json'));

  for (const file of logFiles) {
    const filePath = path.join(logsDir, file);
    const stat = fs.statSync(filePath);
    if (!stat.isFile()) continue;

    let result;
    if (stat.size > STREAMING_THRESHOLD) {
      // Use streaming for large files to avoid memory issues
      console.log(`  Processing large file (${(stat.size / 1024 / 1024).toFixed(1)} MB): ${file}`);
      result = await sanitizeFileStreaming(filePath);
    } else {
      result = sanitizeFileInMemory(filePath);
    }

    totalRemoved += result.removed;
    totalFixed += result.fixed;
  }

  return { removed: totalRemoved, fixed: totalFixed };
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
    // Step 0: Sanitize logs (remove malformed entries, fix escaped quotes for befaas)
    console.log('\nStep 0: Sanitizing logs...');
    const sanitizeResult = await sanitizeLogs(absoluteLogsDir);
    if (sanitizeResult.removed > 0) {
      console.log(`  Removed ${sanitizeResult.removed} malformed log entries`);
    }
    if (sanitizeResult.fixed > 0) {
      console.log(`  Cleaned ${sanitizeResult.fixed} BEFAAS entries (removed prefixes/escape fixes)`);
    }
    if (sanitizeResult.removed === 0 && sanitizeResult.fixed === 0) {
      console.log('  All log entries are valid');
    }

    // Step 0.5: Sync deployment_id.txt with artillery.log
    // The befaas/analysis container filters by deployment_id.txt, so it must match the logs
    const artilleryLog = path.join(absoluteLogsDir, 'artillery.log');
    const deploymentIdFile = path.join(absoluteLogsDir, 'deployment_id.txt');
    if (fs.existsSync(artilleryLog)) {
      const artilleryContent = fs.readFileSync(artilleryLog, 'utf8');
      const match = artilleryContent.match(/"deploymentId":"([^"]+)"/);
      if (match) {
        const logDeploymentId = match[1];
        const currentId = fs.existsSync(deploymentIdFile)
          ? fs.readFileSync(deploymentIdFile, 'utf8').trim()
          : '';
        if (currentId !== logDeploymentId) {
          console.log(`  Syncing deployment_id.txt: ${currentId || '(empty)'} -> ${logDeploymentId}`);
          fs.writeFileSync(deploymentIdFile, logDeploymentId);
        }
      }
    }

    // Step 1: Generate dump.json using befaas/analysis container
    console.log('\nStep 1: Generating dump.json from logs...');
    const containerLogsDir = `/experiments/${path.relative(projectRoot, absoluteLogsDir)}`;
    const containerAnalysisDir = `/experiments/${path.relative(projectRoot, absoluteAnalysisDir)}`;

    const dumpFile = path.join(analysisDir, 'dump.json');

    execSync(`docker run --rm -v "${projectRoot}":/experiments befaas/analysis "${containerLogsDir}" "${containerAnalysisDir}"`, {
      stdio: 'inherit',
      shell: '/bin/bash'
    });

    // Check if dump.json was created and has content
    if (!fs.existsSync(dumpFile)) {
      console.log('dump.json not created by container, skipping further analysis');
      return;
    }

    let dumpContent = fs.readFileSync(dumpFile, 'utf8').trim();
    if (dumpContent === '[]' || dumpContent === '{}' || dumpContent.length < 10) {
      console.log('dump.json is empty, skipping further analysis');
      return;
    }

    // Fix incomplete JSON array (befaas/analysis container bug)
    if (!dumpContent.endsWith(']')) {
      console.log('  Fixing incomplete dump.json (missing closing bracket)');
      fs.appendFileSync(dumpFile, ']');
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

    // Step 3: Analyze logs for auth metrics, cold starts, and memory usage
    console.log('\nStep 3: Analyzing logs for auth & Lambda metrics...');
    try {
      const logAnalysis = await analyzeExperimentLogs(outputDir);
      if (logAnalysis) {
        if (logAnalysis.auth_metrics) {
          console.log('  Auth metrics analysis complete');
        }
        if (logAnalysis.lambda_metrics) {
          console.log('  Lambda metrics analysis complete');
        }
      }
    } catch (logError) {
      console.error('Log analysis failed:', logError.message);
      // Continue - log analysis is supplementary
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
    console.log('  - log-analysis.json: Auth success/failure rates and Lambda metrics');
    console.log('    - Auth request success/failure by endpoint and phase');
    console.log('    - Cold start count, frequency, and duration');
    console.log('    - Memory usage efficiency and right-sizing recommendations');

  } catch (error) {
    console.error('Analysis failed:', error.message);
    console.log('Note: Analysis requires Docker and the befaas/analysis image');
    // Don't throw - analysis is optional
  }
}

module.exports = {
  analyzeResults
};