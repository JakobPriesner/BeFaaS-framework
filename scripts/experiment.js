#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');

// Import modules
const { parseArgs, validateConfig } = require('./experiment/config');
const { validateEnvironment, setHardwareConfig, installTerraformProviders } = require('./experiment/env');
const { runBuild } = require('./experiment/build');
const { runDeploy, runDestroy, resetCognitoUserPool, forceDestroyRedis } = require('./experiment/deploy');
const { runBenchmark } = require('./experiment/benchmark');
const { collectMetrics } = require('./experiment/metrics');
const { collectCloudWatchMetrics } = require('./experiment/cloudwatch-metrics');
const { cleanupOldLogGroupsForRun, cleanupAllOrphanedLogGroups, cleanupAllEdgeLambdaLogs } = require('./experiment/lambda-logs');
const { collectPricingMetrics } = require('./experiment/pricing');
const { analyzeResults } = require('./experiment/analysis');
const {
  S3_BUCKET_NAME,
  logSection,
  checkHealth,
  cleanupBuildArtifacts,
  uploadResultsToS3,
  setupLogging,
  parseCpuInfoFromLogs
} = require('./experiment/utils');
const { getTerraformOutputJson } = require('./deploy-shared');

// Note: Redis preregistration now runs on the workload EC2 instance
// inside the Docker container (see artillery/preregister-redis.js)

/**
 * Prompt user for confirmation before continuing
 * @param {string} message - Message to display to user
 * @returns {Promise<boolean>} - True if user confirms, false otherwise
 */
async function waitForUserConfirmation(message) {
  console.warn(`\n⚠️  ${message}`);
  console.warn('Continuing automatically after 10 seconds...');
  await new Promise(resolve => setTimeout(resolve, 10000));
  return true;
}

/**
 * Read per-service scaling config from Terraform outputs and write to hardware_config.json.
 * Called after terraform deploy so we capture actual values (defaults or overrides).
 * @param {Object} config - Experiment configuration
 * @param {string} hardwareConfigDir - Path to the directory containing hardware_config.json
 */
function updateHardwareConfigWithScalingRules(config, hardwareConfigDir) {
  const hardwareConfigFile = path.join(hardwareConfigDir, 'hardware_config.json');
  if (!fs.existsSync(hardwareConfigFile)) {
    console.log('hardware_config.json not found, skipping scaling rules update');
    return;
  }

  const projectRoot = path.join(__dirname, '..');
  let terraformDir;

  if (config.architecture === 'monolith') {
    terraformDir = path.join(projectRoot, 'infrastructure', 'monolith', 'aws');
  } else if (config.architecture === 'microservices') {
    terraformDir = path.join(projectRoot, 'infrastructure', 'microservices', 'aws');
  } else {
    // FaaS has no ECS scaling rules
    return;
  }

  try {
    const output = getTerraformOutputJson(terraformDir);
    const scalingConfig = output.scaling_config?.value;

    if (!scalingConfig) {
      console.log('No scaling_config output from Terraform, skipping');
      return;
    }

    const hardwareConfig = JSON.parse(fs.readFileSync(hardwareConfigFile, 'utf8'));
    hardwareConfig.services = scalingConfig;
    fs.writeFileSync(hardwareConfigFile, JSON.stringify(hardwareConfig, null, 2));

    const serviceCount = Object.keys(scalingConfig).length;
    const ruleCount = Object.values(scalingConfig).reduce(
      (sum, svc) => sum + Object.keys(svc.scaling_rules || {}).length, 0
    );
    console.log(`✓ Updated hardware_config.json with scaling rules (${serviceCount} services, ${ruleCount} rules)`);
  } catch (error) {
    console.warn('Warning: Could not read scaling config from Terraform:', error.message);
  }
}

/**
 * Update hardware_config.json with CPU info parsed from collected logs
 * @param {string} logsDir - Path to the logs directory (containing aws.log)
 * @param {string} hardwareConfigDir - Path to the directory containing hardware_config.json
 */
async function updateHardwareConfigWithCpuInfo(logsDir, hardwareConfigDir) {
  const cpuInfo = await parseCpuInfoFromLogs(logsDir);
  if (!cpuInfo) {
    console.log('No CPU info found in logs');
    return;
  }

  const hardwareConfigFile = path.join(hardwareConfigDir, 'hardware_config.json');
  if (!fs.existsSync(hardwareConfigFile)) {
    console.log('hardware_config.json not found, skipping CPU info update');
    return;
  }

  try {
    const hardwareConfig = JSON.parse(fs.readFileSync(hardwareConfigFile, 'utf8'));
    hardwareConfig.service_cpu_info = cpuInfo;
    fs.writeFileSync(hardwareConfigFile, JSON.stringify(hardwareConfig, null, 2));
    console.log(`✓ Updated hardware_config.json with service CPU info: ${cpuInfo.model_name || 'unknown'}`);
  } catch (error) {
    console.warn('Warning: Could not update hardware_config.json with CPU info:', error.message);
  }
}

async function main() {
  // Parse and validate configuration
  const args = process.argv.slice(2);
  const config = validateConfig(parseArgs(args));

  // Handle --cleanup-logs mode (cleanup orphaned log groups and exit)
  if (config.cleanupLogs) {
    logSection('Cleaning Up ALL Orphaned CloudWatch Log Groups');
    await cleanupAllOrphanedLogGroups();
    console.log('\n✓ Cleanup complete. Exiting.');
    process.exit(0);
  }

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
  if (config.algorithm) {
    console.log(`  Algorithm: ${config.algorithm}`);
  }
  if (config.withCloudfront) {
    console.log(`  CloudFront Proxy: enabled (passthrough)`);
  }

  // Hardware configuration
  if (config.architecture === 'faas') {
    console.log(`  Lambda Memory: ${config.memory} MB`);
  } else {
    console.log(`  Fargate CPU: ${config.cpu} units (${config.cpu / 1024} vCPU)`);
    console.log(`  Fargate Memory: ${config.memoryFargate} MB`);
    console.log(`  Scaling Mode: ${config.scalingMode}`);
  }

  console.log(`  Workload: ${config.workload}`);
  console.log(`  Run ID: ${config.runId}`);
  console.log(`  Output Directory: ${config.outputDir}`);
  console.log(`  Log File: ${logFile}`);

  let buildDir = null;
  let experimentStartTime = null;

  try {
    // Step 0: Validate environment, set hardware config, and install Terraform providers
    validateEnvironment(config.experiment);
    setHardwareConfig(config);
    installTerraformProviders(config.experiment);

    // Skip all pre-benchmark steps if --skip-benchmark is set
    if (!config.skipBenchmark) {
      // Step 1: Cleanup and destroy existing infrastructure
      cleanupBuildArtifacts(config.experiment, config.architecture);

      try {
        // Force destroy Redis containers first to prevent hanging
        try {
          await forceDestroyRedis(config.experiment);
        } catch (redisError) {
          console.warn('Warning: Could not force destroy Redis:', redisError.message);
        }

        await runDestroy(config.experiment, config.architecture, config.auth, { skipEdgeAuth: config.reuseEdgeAuth, withCloudfront: config.withCloudfront });
      } catch (error) {
        console.log('No existing infrastructure to destroy or destroy failed:', error.message);
      }

      // Clean up old CloudWatch log groups for this run_id (FaaS only)
      // This ensures we start with clean logs even if a previous run failed
      if (config.architecture === 'faas') {
        logSection('Cleaning Up Old CloudWatch Logs');
        await cleanupOldLogGroupsForRun(config.runId);
      }

      // Step 2: Build
      // Map edge-selective to edge for build (same auth code, only CloudFront routing differs)
      const buildAuth = config.auth === 'edge-selective' ? 'edge' : config.auth;
      buildDir = await runBuild(config.experiment, config.architecture, buildAuth, config.algorithm);

      // Step 3: Deploy
      // Record experiment start time (in milliseconds for AWS CloudWatch)
      // Subtract 1 minute buffer to ensure we capture initialization logs
      experimentStartTime = Date.now() - 60000;

      // Write timestamp to file for reference
      const timestampFile = path.join(config.outputDir, 'experiment_start_time.txt');
      fs.writeFileSync(timestampFile, `${experimentStartTime}\n${new Date(experimentStartTime).toISOString()}`);
      console.log(`Experiment start time recorded: ${new Date(experimentStartTime).toISOString()}`);

      // Write hardware configuration
      const hardwareConfig = {
        architecture: config.architecture,
        auth_strategy: config.auth,
        aws_service: config.architecture === 'faas' ? 'lambda' : 'ecs fargate',
        ram_in_mb: config.architecture === 'faas' ? config.memory : config.memoryFargate,
        with_cloudfront: config.withCloudfront,
        datetime: config.runId.split('_').pop() // Extract timestamp from runId
      };
      if (config.architecture !== 'faas') {
        hardwareConfig.cpu_in_vcpu = config.cpu / 1024;
        hardwareConfig.scaling_mode = config.scalingMode;
      }
      if (config.algorithm) {
        const algorithmMap = {
          'bcrypt-hs256': { password_hash_algorithm: 'bcrypt', jwt_sign_algorithm: 'HS256' },
          'argon2id-eddsa': { password_hash_algorithm: 'argon2id', jwt_sign_algorithm: 'EdDSA' }
        };
        const algConfig = algorithmMap[config.algorithm];
        if (algConfig) {
          hardwareConfig.password_hash_algorithm = algConfig.password_hash_algorithm;
          hardwareConfig.jwt_sign_algorithm = algConfig.jwt_sign_algorithm;
        }
      }
      const hardwareConfigFile = path.join(config.outputDir, 'hardware_config.json');
      fs.writeFileSync(hardwareConfigFile, JSON.stringify(hardwareConfig, null, 2));
      console.log(`Hardware config written: ${hardwareConfigFile}`);

      // Write benchmark configuration - read timeout from workload YAML
      const workloadFile = path.join(__dirname, '..', 'experiments', config.experiment, config.workload);
      const workloadYaml = yaml.load(fs.readFileSync(workloadFile, 'utf8'));
      const benchmarkConfig = {
        http_timeout_in_seconds: workloadYaml.config && workloadYaml.config.http && workloadYaml.config.http.timeout || 10
      };
      const benchmarkConfigFile = path.join(config.outputDir, 'benchmark_configuration.json');
      fs.writeFileSync(benchmarkConfigFile, JSON.stringify(benchmarkConfig, null, 2));
      console.log(`Benchmark config written: ${benchmarkConfigFile}`);

      // Create empty error description file (will be populated if error occurs)
      const errorDescFile = path.join(config.outputDir, 'error_description.md');
      fs.writeFileSync(errorDescFile, '');
      console.log(`Error description file created: ${errorDescFile}`);

      // Set run_id for Terraform (used for CloudWatch log group naming)
      process.env.TF_VAR_run_id = config.runId;
      console.log(`Run ID: ${config.runId}`);

      const endpoints = await runDeploy(config.experiment, config.architecture, buildDir, config.auth, config.algorithm, config.reuseEdgeAuth, config.withCloudfront);

      // Capture per-service scaling rules from Terraform state into hardware_config.json
      updateHardwareConfigWithScalingRules(config, config.outputDir);

      // Wait for deployment to stabilize
      const isEcsBased = config.architecture === 'monolith' || config.architecture === 'microservices';
      const isEdgeAuth = config.auth === 'edge' || config.auth === 'edge-selective';
      const hasCloudfront = isEdgeAuth || config.withCloudfront;
      // CloudFront takes longer to propagate (3-5 min creation + propagation time)
      const stabilizationDelay = isEcsBased ? 180000 : (hasCloudfront ? 60000 : 5000); // 3 min for ecs, 1 min for edge/cf, 5s for Lambda
      const healthCheckRetries = 120;
      const healthCheckDelay = isEcsBased ? 30000 : 3000; // 30s for ecs, 3s for Lambda

      console.log(`\nWaiting for deployment to stabilize (${stabilizationDelay / 1000}s)...`);
      await new Promise(resolve => setTimeout(resolve, stabilizationDelay));

      // Health check
      const isHealthy = await checkHealth(endpoints, healthCheckRetries, healthCheckDelay);
      if (!isHealthy) {
        throw new Error('Deployment failed health check');
      }

      // Note: Redis user preregistration now runs on the workload EC2 instance
      // inside the Docker container (see artillery/preregister-redis.js)
      // The AUTH_MODE env var is passed via workload.sh -> terraform

      // Step 4-7: Run Benchmark
      await resetCognitoUserPool();
      await runBenchmark(config.experiment, config.workload, config.outputDir, config.auth, config.architecture, config.algorithm);

      // Record end time (add 1 minute buffer to capture trailing metrics)
      const experimentEndTime = Date.now() + 60000;

      if (!config.skipMetrics) {
        await collectMetrics(config.experiment, config.outputDir, experimentStartTime, config.architecture, config.auth);

        // Note: Lambda log collection for FaaS is already handled by collectMetrics()
        // Do NOT call collectAndCleanupLambdaLogs() again here - it would overwrite the logs!

        // Collect CloudWatch metrics for all architectures
        await collectCloudWatchMetrics(config, config.outputDir, experimentStartTime, experimentEndTime);

        // Collect pricing metrics for all architectures
        await collectPricingMetrics(config, config.outputDir, experimentStartTime, experimentEndTime);
      }

      // Update hardware_config.json with CPU info from collected logs
      await updateHardwareConfigWithCpuInfo(path.join(config.outputDir, 'logs'), config.outputDir);

      await analyzeResults(config.experiment, config.outputDir);
    }

    // Step 8: Destroy infrastructure if requested
    let destroyFailed = false;
    if (config.destroy) {
      try {
        await runDestroy(config.experiment, config.architecture, config.auth, { skipEdgeAuth: config.keepEdgeAuth, withCloudfront: config.withCloudfront });
        cleanupBuildArtifacts(config.experiment, config.architecture);
      } catch (destroyError) {
        destroyFailed = true;
        console.error('\n⚠️  Infrastructure destruction failed:', destroyError.message);
        console.log('Analysis has already been completed. Results are available in the output directory.');
        console.log('You may need to manually destroy the infrastructure or retry later.');
        await waitForUserConfirmation('Infrastructure destruction failed. Please verify AWS resources are cleaned up.');
      }

      // Step 9: Clean up CloudWatch log groups AFTER terraform destroy
      // This ensures Lambda functions are stopped before we delete their log groups
      // (Lambda auto-recreates log groups if they're deleted while functions are still running)
      if (config.architecture === 'faas' && config.runId) {
        logSection('Cleaning Up CloudWatch Log Groups');
        try {
          await cleanupOldLogGroupsForRun(config.runId);
        } catch (logError) {
          console.warn('Warning: Could not cleanup CloudWatch logs:', logError.message);
        }
      }

      // Clean up Lambda@Edge log groups if edge auth was used
      if ((config.auth === 'edge' || config.auth === 'edge-selective') && !config.keepEdgeAuth) {
        logSection('Cleaning Up Lambda@Edge Log Groups');
        try {
          await cleanupAllEdgeLambdaLogs();
        } catch (edgeLogError) {
          console.warn('Warning: Could not cleanup Lambda@Edge logs:', edgeLogError.message);
        }
      }
    }

    // Step 10: Upload results to S3
    const uploadSuccess = await uploadResultsToS3(
      config.outputDir,
      config.experiment,
      config.architecture,
      config.auth
    );

    // Step 10: Delete local results after successful upload
    if (uploadSuccess) {
      // deleteLocalResults(config.outputDir);
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

    // Write error description to file
    const errorDescFile = path.join(config.outputDir, 'error_description.md');
    const errorContent = `# Experiment Error

**Error:** ${error.message}

**Timestamp:** ${new Date().toISOString()}

## Stack Trace
\`\`\`
${error.stack}
\`\`\`

## Configuration
- Architecture: ${config.architecture}
- Auth Strategy: ${config.auth}
- Run ID: ${config.runId}
`;
    try {
      fs.writeFileSync(errorDescFile, errorContent);
      console.log(`Error description written to: ${errorDescFile}`);
    } catch (writeError) {
      console.warn('Warning: Could not write error description:', writeError.message);
    }

    // IMPORTANT: Collect logs/metrics BEFORE destroying infrastructure
    // This ensures we capture all data even if cleanup fails
    console.log('\nAttempting to collect logs and metrics before cleanup...');

    // Get experiment timestamps for log collection
    const errorRecoveryStartTime = experimentStartTime || Date.now() - 3600000; // Use recorded start time or 1 hour ago
    const errorRecoveryEndTime = Date.now() + 60000; // 1 minute buffer

    // Try to collect metrics (CloudWatch logs, Lambda logs, ECS logs)
    try {
      console.log('Collecting metrics...');
      await collectMetrics(config.experiment, config.outputDir, errorRecoveryStartTime, config.architecture, config.auth);
      console.log('✓ Metrics collection completed');
    } catch (metricsError) {
      console.warn('Warning: Could not collect metrics:', metricsError.message);
    }

    // Try to collect CloudWatch metrics
    try {
      console.log('Collecting CloudWatch metrics...');
      await collectCloudWatchMetrics(config, config.outputDir, errorRecoveryStartTime, errorRecoveryEndTime);
      console.log('✓ CloudWatch metrics collection completed');
    } catch (cwError) {
      console.warn('Warning: Could not collect CloudWatch metrics:', cwError.message);
    }

    // Try to collect pricing metrics
    try {
      console.log('Collecting pricing metrics...');
      await collectPricingMetrics(config, config.outputDir, errorRecoveryStartTime, errorRecoveryEndTime);
      console.log('✓ Pricing metrics collection completed');
    } catch (pricingError) {
      console.warn('Warning: Could not collect pricing metrics:', pricingError.message);
    }

    // Try to run analysis on collected logs
    console.log('\nAttempting to analyze collected logs...');
    try {
      await analyzeResults(config.experiment, config.outputDir);
      console.log('✓ Analysis completed on available logs');
    } catch (analysisError) {
      console.warn('Warning: Could not run analysis:', analysisError.message);
    }

    // Cleanup and destroy on error (logs already collected, so this can fail safely)
    console.log('\nCleaning up infrastructure...');
    try {
      // Force destroy Redis containers first to prevent hanging
      console.log('Force destroying Redis containers...');
      try {
        await forceDestroyRedis(config.experiment);
      } catch (redisError) {
        console.warn('Warning: Could not force destroy Redis:', redisError.message);
      }

      // Destroy infrastructure (logs already collected)
      await runDestroy(config.experiment, config.architecture, config.auth, { skipEdgeAuth: config.keepEdgeAuth, withCloudfront: config.withCloudfront });
      cleanupBuildArtifacts(config.experiment, config.architecture);

      // Clean up CloudWatch log groups AFTER terraform destroy
      // (Lambda auto-recreates log groups if they're deleted while functions are still running)
      if (config.architecture === 'faas' && config.runId) {
        console.log('Cleaning up CloudWatch log groups...');
        try {
          await cleanupOldLogGroupsForRun(config.runId);
        } catch (logError) {
          console.warn('Warning: Could not cleanup CloudWatch logs:', logError.message);
        }
      }

      // Clean up Lambda@Edge log groups if edge auth was used
      if ((config.auth === 'edge' || config.auth === 'edge-selective') && !config.keepEdgeAuth) {
        console.log('Cleaning up Lambda@Edge log groups...');
        try {
          await cleanupAllEdgeLambdaLogs();
        } catch (edgeLogError) {
          console.warn('Warning: Could not cleanup Lambda@Edge logs:', edgeLogError.message);
        }
      }
    } catch (cleanupError) {
      console.error('\n⚠️  Infrastructure cleanup failed:', cleanupError.message);
      console.log('Logs and metrics have been collected and analyzed.');
      console.log('You may need to manually destroy the infrastructure or retry later.');
      await waitForUserConfirmation('Infrastructure cleanup failed. Please verify AWS resources are cleaned up before continuing.');
    }

    process.exit(1);
  }
}

main();