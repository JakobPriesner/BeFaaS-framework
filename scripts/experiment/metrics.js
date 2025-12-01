const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { spawn } = require('child_process');
const { logSection } = require('./utils');

async function collectMetrics(experiment, outputDir, experimentStartTime) {
  logSection('Collecting Logs and Metrics');

  const projectRoot = path.join(__dirname, '..', '..');
  const logsScript = path.join(projectRoot, 'scripts', 'logs.sh');
  const experimentJsonPath = path.join(projectRoot, 'experiments', experiment, 'experiment.json');

  if (!fs.existsSync(experimentJsonPath)) {
    console.log('No experiment.json found, skipping logs collection');
    return;
  }

  try {
    console.log('Running logs collection script...');

    // Get AWS region from endpoint infrastructure
    let awsRegion = process.env.AWS_REGION || process.env.AWS_DEFAULT_REGION || 'us-east-1';
    try {
      const endpointDir = path.join(projectRoot, 'infrastructure', 'aws', 'endpoint');
      if (fs.existsSync(path.join(endpointDir, 'terraform.tfstate'))) {
        const regionOutput = execSync('terraform output -json', {
          cwd: endpointDir,
          encoding: 'utf8'
        });
        const outputs = JSON.parse(regionOutput);
        if (outputs.AWS_LAMBDA_ENDPOINT && outputs.AWS_LAMBDA_ENDPOINT.value) {
          // Extract region from endpoint URL: https://{api-id}.execute-api.{region}.amazonaws.com/dev
          const match = outputs.AWS_LAMBDA_ENDPOINT.value.match(/execute-api\.([^.]+)\.amazonaws\.com/);
          if (match) {
            awsRegion = match[1];
          }
        }
      }
    } catch (error) {
      console.log(`Could not determine AWS region, using default: ${awsRegion}`);
    }

    console.log(`Using AWS region: ${awsRegion}`);

    // Prepare environment with experiment start time
    const logsEnv = {
      ...process.env,
      AWS_REGION: awsRegion
    };

    // Add experiment start time if available
    if (experimentStartTime) {
      logsEnv.EXPERIMENT_START_TIME = experimentStartTime.toString();
      console.log(`Filtering logs from: ${new Date(experimentStartTime).toISOString()}`);
    }

    // Run logs.sh to collect logs from providers (must run from project root)
    await new Promise((resolve, reject) => {
      const child = spawn(logsScript, [experiment, 'experiment.json'], {
        cwd: projectRoot,
        stdio: ['inherit', 'inherit', 'inherit'],
        shell: '/bin/bash',
        env: logsEnv
      });

      child.on('close', (code) => {
        if (code !== 0) {
          reject(new Error(`Logs collection script exited with code ${code}`));
        } else {
          resolve();
        }
      });

      child.on('error', (error) => {
        reject(new Error(`Failed to start logs collection script: ${error.message}`));
      });
    });

    // Copy collected logs to output directory
    const logsDir = path.join(projectRoot, 'logs', experiment);
    if (fs.existsSync(logsDir)) {
      // Get the most recent logs directory
      const logDirs = fs.readdirSync(logsDir).sort().reverse();
      if (logDirs.length > 0) {
        const latestLogDir = path.join(logsDir, logDirs[0]);
        const destLogsDir = path.join(outputDir, 'logs');

        console.log(`Copying logs from ${latestLogDir} to ${destLogsDir}`);

        // Copy logs to output directory
        if (!fs.existsSync(destLogsDir)) {
          fs.mkdirSync(destLogsDir, { recursive: true });
        }

        // Copy all files from latest log dir
        const files = fs.readdirSync(latestLogDir);
        for (const file of files) {
          const srcFile = path.join(latestLogDir, file);
          const destFile = path.join(destLogsDir, file);
          fs.copyFileSync(srcFile, destFile);
        }

        console.log('✓ Logs collected and copied to output directory');
      }
    }

    console.log('✓ Metrics collection completed');
  } catch (error) {
    console.error('✗ Metrics collection failed:', error.message);
    // Don't throw - logs collection is not critical
  }
}

module.exports = {
  collectMetrics
};