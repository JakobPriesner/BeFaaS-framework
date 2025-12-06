const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { logSection } = require('./utils');

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
    // Step 1: Generate dump.json using befaas/analysis container
    console.log('\nStep 1: Generating dump.json from logs...');
    const containerLogsDir = `/experiments/${path.relative(projectRoot, absoluteLogsDir)}`;
    const containerAnalysisDir = `/experiments/${path.relative(projectRoot, absoluteAnalysisDir)}`;

    execSync(`docker run --rm -v ${projectRoot}:/experiments befaas/analysis ${containerLogsDir} ${containerAnalysisDir}`, {
      stdio: 'inherit',
      shell: '/bin/bash'
    });

    const dumpFile = path.join(analysisDir, 'dump.json');
    if (!fs.existsSync(dumpFile)) {
      console.log('⚠️  dump.json not created, skipping further analysis');
      return;
    }

    console.log('✓ dump.json generated successfully');

    // Step 2: Generate performance plots
    console.log('\nStep 2: Generating performance plots...');
    const generatePlotsScript = path.join(projectRoot, 'scripts', 'generate_plots.py');
    const requirementsFile = path.join(projectRoot, 'scripts', 'requirements.txt');

    if (fs.existsSync(generatePlotsScript)) {
      try {
        // Check if required Python packages are installed
        try {
          execSync('python3 -c "import matplotlib; import numpy; import scipy; import networkx"', {
            stdio: 'pipe'
          });
        } catch (importError) {
          console.log('Installing Python dependencies...');
          if (fs.existsSync(requirementsFile)) {
            execSync(`pip3 install -r ${requirementsFile}`, { stdio: 'inherit' });
          } else {
            execSync('pip3 install matplotlib numpy scipy networkx', { stdio: 'inherit' });
          }
        }

        execSync(`python3 ${generatePlotsScript} ${dumpFile} ${analysisDir}`, {
          stdio: 'inherit'
        });
        console.log('✓ Performance plots generated');

        // Check if this is a stress test phase and generate stress-specific plots
        const isStressTest = outputDir.includes('stress-ramp') || outputDir.includes('stress-auth');
        if (isStressTest) {
          console.log('\nGenerating stress test specific plots...');
          try {
            execSync(`python3 ${generatePlotsScript} --stress ${dumpFile} ${analysisDir}`, {
              stdio: 'inherit'
            });
            console.log('✓ Stress test plots generated');
          } catch (stressError) {
            console.error('⚠️  Stress test plot generation failed:', stressError.message);
          }
        }
      } catch (error) {
        console.error('⚠️  Performance plot generation failed:', error.message);
        console.log('   Try: pip3 install -r scripts/requirements.txt');
      }
    } else {
      console.log('⚠️  generate_plots.py not found, skipping performance plots');
    }

    // Step 3: Validate HTTP responses
    console.log('\nStep 3: Validating HTTP responses...');
    const validateScript = path.join(projectRoot, 'scripts', 'validate_responses.py');
    const artilleryLog = path.join(logsDir, 'artillery.log');

    if (fs.existsSync(validateScript) && fs.existsSync(artilleryLog)) {
      try {
        execSync(`python3 ${validateScript} ${artilleryLog} ${analysisDir}`, {
          stdio: 'inherit'
        });
        console.log('✓ HTTP response validation completed');
      } catch (error) {
        // Exit code 1 or 2 means warnings/errors were found but analysis completed
        if (error.status === 1 || error.status === 2) {
          console.log('✓ HTTP response validation completed (with warnings)');
        } else {
          console.error('⚠️  HTTP response validation failed:', error.message);
        }
      }
    } else {
      if (!fs.existsSync(artilleryLog)) {
        console.log('⚠️  artillery.log not found, skipping HTTP validation');
      } else {
        console.log('⚠️  validate_responses.py not found, skipping HTTP validation');
      }
    }

    // Step 4: Analyze AWS CloudWatch errors
    console.log('\nStep 4: Analyzing AWS CloudWatch errors...');
    const analyzeErrorsScript = path.join(projectRoot, 'scripts', 'analyze_errors.py');
    const awsLog = path.join(logsDir, 'aws.log');

    if (fs.existsSync(analyzeErrorsScript) && fs.existsSync(awsLog)) {
      try {
        execSync(`python3 ${analyzeErrorsScript} ${awsLog} ${analysisDir}`, {
          stdio: 'inherit'
        });
        console.log('✓ Error analysis completed');
      } catch (error) {
        // Exit code 1 or 2 means errors were found but analysis completed
        if (error.status === 1 || error.status === 2) {
          console.log('✓ Error analysis completed (issues found)');
        } else {
          console.error('⚠️  Error analysis failed:', error.message);
        }
      }
    } else {
      if (!fs.existsSync(awsLog)) {
        console.log('⚠️  aws.log not found, skipping error analysis');
      } else {
        console.log('⚠️  analyze_errors.py not found, skipping error analysis');
      }
    }

    console.log('\n✓ Analysis completed successfully');
    console.log(`\nAnalysis results saved to: ${analysisDir}`);
    console.log('  - dump.json: Raw performance data');
    console.log('  - insights.json: Statistics for cross-run comparison');
    console.log('  - validation_report.txt: HTTP response analysis');
    console.log('  - error_analysis.txt: AWS CloudWatch error analysis');
    console.log('  Performance Plots:');
    console.log('    - response_time_*.png: Overall response time analysis');
    console.log('    - endpoint_*.png: Per-endpoint performance');
    console.log('    - category_*.png: Performance by category');
    console.log('    - function_*.png: Function/microservice analysis');
    console.log('    - callgraph_*.png: Function call graph visualizations');
    console.log('    - auth_*.png: Authentication overhead analysis');

    // Show stress test plots info if applicable
    const isStressTestOutput = outputDir.includes('stress-ramp') || outputDir.includes('stress-auth');
    if (isStressTestOutput) {
      console.log('  Stress Test Plots:');
      console.log('    - stress_response_vs_load.png: Response time vs concurrent requests');
      console.log('    - stress_scaling_timeline.png: Load profile and latency over time');
      console.log('    - stress_latency_buckets.png: Latency distribution at different loads');
      console.log('    - stress_throughput_vs_latency.png: Throughput vs latency curve');
      console.log('    - stress_summary.png: Summary dashboard');
    }

  } catch (error) {
    console.error('✗ Analysis failed:', error.message);
    console.log('Note: Analysis requires Docker and the befaas/analysis image');
    // Don't throw - analysis is optional
  }
}

module.exports = {
  analyzeResults
};