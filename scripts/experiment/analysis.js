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

    if (fs.existsSync(generatePlotsScript)) {
      try {
        execSync(`python3 ${generatePlotsScript} ${dumpFile} ${analysisDir}`, {
          stdio: 'inherit'
        });
        console.log('✓ Performance plots generated');
      } catch (error) {
        console.error('⚠️  Performance plot generation failed:', error.message);
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
    console.log('  - *.png: Performance visualizations');
    console.log('  - validation_report.txt: HTTP response analysis');
    console.log('  - error_analysis.txt: AWS CloudWatch error analysis');

  } catch (error) {
    console.error('✗ Analysis failed:', error.message);
    console.log('Note: Analysis requires Docker and the befaas/analysis image');
    // Don't throw - analysis is optional
  }
}

module.exports = {
  analyzeResults
};