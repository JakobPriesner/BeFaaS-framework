#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

// Import modules
const { parseArgs, validateConfig } = require('./experiment/config');
const { validateEnvironment, setHardwareConfig, installTerraformProviders } = require('./experiment/env');
const { runBuild } = require('./experiment/build');
const { runDeploy, runDestroy, resetCognitoUserPool } = require('./experiment/deploy');
const { runBenchmark } = require('./experiment/benchmark');
const { collectMetrics } = require('./experiment/metrics');
const { analyzeResults } = require('./experiment/analysis');
const {
  S3_BUCKET_NAME,
  logSection,
  checkHealth,
  cleanupBuildArtifacts,
  uploadResultsToS3,
  setupLogging
} = require('./experiment/utils');

async function main() {
  // Parse and validate configuration
  const args = process.argv.slice(2);
  const config = validateConfig(parseArgs(args));

  // Create output directory early
  if (!fs.existsSync(config.outputDir)) {
    fs.mkdirSync(config.outputDir, { recursive: true });
  }

  // Setup logging to file
  const logFile = setupLogging(config.outputDir);

  console.log('Experiment Configuration:');
  console.log(`  Experiment: ${config.experiment}`);
  console.log(`  Architecture: ${config.architecture}`);
  console.log(`  Auth Strategy: ${config.auth}`);
  console.log(`  Lambda Memory: ${config.memory} MB`);
  console.log(`  Workload: ${config.workload}`);
  console.log(`  Output Directory: ${config.outputDir}`);
  console.log(`  Log File: ${logFile}`);

  let buildDir = null;
  let experimentStartTime = null;

  try {
    // Step 0: Validate environment, set hardware config, and install Terraform providers
    validateEnvironment(config.experiment);
    setHardwareConfig(config);
    installTerraformProviders();

    // Step 1: Cleanup and destroy existing infrastructure
    if (!config.deployOnly) {
      cleanupBuildArtifacts(config.experiment, config.architecture);

      try {
        await runDestroy(config.experiment, config.architecture);
      } catch (error) {
        console.log('No existing infrastructure to destroy or destroy failed:', error.message);
      }
    }

    // If destroy-only, just destroy and exit
    if (config.destroyOnly) {
      await runDestroy(config.experiment, config.architecture);
      cleanupBuildArtifacts(config.experiment, config.architecture);
      logSection('Infrastructure Destroyed and Cleaned Up');
      return;
    }

    // Step 2: Build
    if (!config.deployOnly) {
      buildDir = await runBuild(config.experiment, config.architecture, config.auth);
    }

    // Step 3: Deploy
    let endpoints = [];
    if (!config.buildOnly) {
      if (!buildDir) {
        buildDir = path.join(__dirname, '..', 'experiments', config.experiment, 'architectures', config.architecture, '_build');
      }

      // Record experiment start time (in milliseconds for AWS CloudWatch)
      // Subtract 1 minute buffer to ensure we capture initialization logs
      experimentStartTime = Date.now() - 60000;

      // Write timestamp to file for reference
      const timestampFile = path.join(config.outputDir, 'experiment_start_time.txt');
      fs.writeFileSync(timestampFile, `${experimentStartTime}\n${new Date(experimentStartTime).toISOString()}`);
      console.log(`Experiment start time recorded: ${new Date(experimentStartTime).toISOString()}`);

      endpoints = await runDeploy(config.experiment, config.architecture, buildDir);

      // Wait for deployment to stabilize
      const isMonolith = config.architecture === 'monolith';
      const stabilizationDelay = isMonolith ? 180000 : 5000; // 3 min for ECS, 5s for Lambda
      const healthCheckRetries = isMonolith ? 20 : 10;
      const healthCheckDelay = isMonolith ? 10000 : 3000; // 10s between retries for ECS

      console.log(`\nWaiting for deployment to stabilize (${stabilizationDelay / 1000}s)...`);
      await new Promise(resolve => setTimeout(resolve, stabilizationDelay));

      // Health check
      const isHealthy = await checkHealth(endpoints, healthCheckRetries, healthCheckDelay);
      if (!isHealthy) {
        throw new Error('Deployment failed health check');
      }
    }

    // Step 4: Reset Cognito User Pool (ensure clean state for benchmark)
    if (!config.buildOnly && !config.skipBenchmark) {
      await resetCognitoUserPool();
    }

    // Step 5: Run Benchmark
    if (!config.buildOnly && !config.skipBenchmark) {
      await runBenchmark(config.experiment, config.workload, config.outputDir);
    }

    // Step 6: Collect Metrics
    if (!config.buildOnly && !config.skipMetrics) {
      await collectMetrics(config.experiment, config.outputDir, experimentStartTime);
    }

    // Step 7: Analyze Results
    if (!config.buildOnly && !config.skipBenchmark) {
      await analyzeResults(config.experiment, config.outputDir);
    }

    // Step 8: Destroy infrastructure if requested
    if (config.destroy && !config.buildOnly) {
      await runDestroy(config.experiment, config.architecture);
      cleanupBuildArtifacts(config.experiment, config.architecture);
    }

    // Step 9: Upload results to S3
    if (!config.buildOnly) {
      const uploadSuccess = await uploadResultsToS3(
        config.outputDir,
        config.experiment,
        config.architecture,
        config.auth
      );

      // Step 10: Delete local results after successful upload
      // TODO: Uncomment the following lines when ready to enable local file deletion
      // if (uploadSuccess) {
      //   deleteLocalResults(config.outputDir);
      // }
    }

    logSection('Experiment Complete');
    console.log(`Results saved to: ${config.outputDir}`);
    console.log(`Results uploaded to: s3://${S3_BUCKET_NAME}/${config.experiment}/`);
    if (config.destroy) {
      console.log('Infrastructure has been destroyed and cleaned up');
    }

  } catch (error) {
    console.error('\n❌ Experiment failed:', error.message);
    console.error(error.stack);

    // Cleanup and destroy on error
    console.log('\nCleaning up due to error...');
    try {
      await runDestroy(config.experiment, config.architecture);
      cleanupBuildArtifacts(config.experiment, config.architecture);
    } catch (cleanupError) {
      console.error('Error during cleanup:', cleanupError.message);
    }

    process.exit(1);
  }
}

main();