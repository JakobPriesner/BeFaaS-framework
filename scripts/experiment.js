#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const readline = require('readline');
const yaml = require('js-yaml');

// Import modules
const { parseArgs, validateConfig } = require('./experiment/config');
const { validateEnvironment, setHardwareConfig, installTerraformProviders } = require('./experiment/env');
const { runBuild } = require('./experiment/build');
const { runDeploy, runDestroy, resetCognitoUserPool, forceDestroyRedis } = require('./experiment/deploy');
const { runBenchmark } = require('./experiment/benchmark');
const { collectMetrics } = require('./experiment/metrics');
const { collectCloudWatchMetrics } = require('./experiment/cloudwatch-metrics');
const { collectAndCleanupLambdaLogs, cleanupOldLogGroupsForRun, cleanupAllOrphanedLogGroups, cleanupAllEdgeLambdaLogs } = require('./experiment/lambda-logs');
const { collectPricingMetrics } = require('./experiment/pricing');
const { analyzeResults } = require('./experiment/analysis');
const {
  S3_BUCKET_NAME,
  logSection,
  checkHealth,
  cleanupBuildArtifacts,
  uploadResultsToS3,
  deleteLocalResults,
  setupLogging,
  parseCpuInfoFromLogs
} = require('./experiment/utils');
const { getTerraformOutputJson } = require('./deploy-shared');

/**
 * Run a single benchmark phase including benchmark execution, metrics collection, and analysis
 * @param {Object} config - Experiment configuration
 * @param {string} phaseName - Name of the benchmark phase (e.g., 'baseline', 'scaling')
 * @param {string} workload - Workload file to use
 * @param {string} phaseOutputDir - Output directory for this phase
 * @returns {number} - Start timestamp for this phase
 */
async function runBenchmarkPhase(config, phaseName, workload, phaseOutputDir) {
  logSection(`Benchmark Phase: ${phaseName}`);

  // Create phase output directory
  if (!fs.existsSync(phaseOutputDir)) {
    fs.mkdirSync(phaseOutputDir, { recursive: true });
  }

  // Record phase start time (subtract 1 minute buffer)
  const phaseStartTime = Date.now() - 60000;

  // Write timestamp to file for reference
  const timestampFile = path.join(phaseOutputDir, 'experiment_start_time.txt');
  fs.writeFileSync(timestampFile, `${phaseStartTime}\n${new Date(phaseStartTime).toISOString()}`);
  console.log(`Phase start time recorded: ${new Date(phaseStartTime).toISOString()}`);

  // Reset Cognito User Pool before benchmark
  await resetCognitoUserPool();

  // Run benchmark
  await runBenchmark(config.experiment, workload, phaseOutputDir, config.auth, config.architecture);

  // Record phase end time (add 1 minute buffer to capture trailing metrics)
  const phaseEndTime = Date.now() + 60000;

  // Collect metrics
  if (!config.skipMetrics) {
    await collectMetrics(config.experiment, phaseOutputDir, phaseStartTime, config.architecture, config.auth);

    // Note: Lambda log collection for FaaS is already handled by collectMetrics()
    // Do NOT call collectAndCleanupLambdaLogs() again here - it would overwrite the logs!

    // Collect CloudWatch metrics for all architectures
    await collectCloudWatchMetrics(config, phaseOutputDir, phaseStartTime, phaseEndTime);

    // Collect pricing metrics for all architectures
    await collectPricingMetrics(config, phaseOutputDir, phaseStartTime, phaseEndTime);
  }

  // Analyze results
  await analyzeResults(config.experiment, phaseOutputDir);

  return phaseStartTime;
}

// Note: Redis preregistration now runs on the workload EC2 instance
// inside the Docker container (see artillery/preregister-redis.js)

/**
 * Wait for infrastructure to scale down
 * @param {number} seconds - Seconds to wait
 */
async function waitForScaleDown(seconds) {
  logSection(`Waiting for Scale Down (${seconds}s)`);
  console.log(`Allowing ${seconds} seconds for infrastructure to scale down...`);

  const intervalMs = 30000; // Log every 30 seconds
  const totalMs = seconds * 1000;
  let elapsed = 0;

  while (elapsed < totalMs) {
    await new Promise(resolve => setTimeout(resolve, Math.min(intervalMs, totalMs - elapsed)));
    elapsed += intervalMs;
    if (elapsed < totalMs) {
      console.log(`  ${Math.round(elapsed / 1000)}s / ${seconds}s elapsed...`);
    }
  }

  console.log('Scale down wait complete.');
}

/**
 * Combine insights.json from all benchmark phases into a single combined insights file
 * @param {string} outputDir - Root output directory
 * @param {string[]} phases - Array of phase names
 * @param {Object} config - Experiment configuration
 */
function combinePhaseInsights(outputDir, phases, config) {
  logSection('Combining Phase Insights');

  const combinedInsights = {
    meta: {
      generated_at: new Date().toISOString(),
      experiment: config.experiment,
      architecture: config.architecture,
      auth: config.auth,
      memory: config.memory,
      phases: phases
    },
    phases: {},
    comparison: {
      overall: {},
      endpoints: {},
      categories: {}
    },
    pricing: {
      phases: {},
      total: null
    }
  };

  // Load insights from each phase
  for (const phase of phases) {
    const insightsPath = path.join(outputDir, phase, 'analysis', 'insights.json');
    if (fs.existsSync(insightsPath)) {
      try {
        const phaseInsights = JSON.parse(fs.readFileSync(insightsPath, 'utf8'));
        combinedInsights.phases[phase] = phaseInsights;
        console.log(`✓ Loaded insights from ${phase}`);
      } catch (error) {
        console.log(`⚠️  Failed to load insights from ${phase}: ${error.message}`);
      }
    } else {
      console.log(`⚠️  No insights.json found for phase ${phase}`);
    }
  }

  // Generate comparison data across phases
  const loadedPhases = Object.keys(combinedInsights.phases);
  if (loadedPhases.length > 1) {
    console.log('\nGenerating cross-phase comparison...');

    // Compare overall metrics
    combinedInsights.comparison.overall = {};
    for (const phase of loadedPhases) {
      const phaseData = combinedInsights.phases[phase];
      if (phaseData.overall) {
        combinedInsights.comparison.overall[phase] = {
          total_requests: phaseData.overall.total_requests,
          mean_ms: phaseData.overall.mean_ms,
          median_ms: phaseData.overall.median_ms,
          p95_ms: phaseData.overall.p95_ms,
          p99_ms: phaseData.overall.p99_ms
        };
      }
    }

    // Compare endpoints across phases
    const allEndpoints = new Set();
    for (const phase of loadedPhases) {
      const phaseData = combinedInsights.phases[phase];
      if (phaseData.endpoints) {
        Object.keys(phaseData.endpoints).forEach(ep => allEndpoints.add(ep));
      }
    }

    for (const endpoint of allEndpoints) {
      combinedInsights.comparison.endpoints[endpoint] = {};
      for (const phase of loadedPhases) {
        const phaseData = combinedInsights.phases[phase];
        if (phaseData.endpoints && phaseData.endpoints[endpoint]) {
          combinedInsights.comparison.endpoints[endpoint][phase] = {
            request_count: phaseData.endpoints[endpoint].request_count,
            mean_ms: phaseData.endpoints[endpoint].mean_ms,
            p95_ms: phaseData.endpoints[endpoint].p95_ms
          };
        }
      }
    }

    // Compare categories across phases
    const allCategories = new Set();
    for (const phase of loadedPhases) {
      const phaseData = combinedInsights.phases[phase];
      if (phaseData.categories) {
        Object.keys(phaseData.categories).forEach(cat => allCategories.add(cat));
      }
    }

    for (const category of allCategories) {
      combinedInsights.comparison.categories[category] = {};
      for (const phase of loadedPhases) {
        const phaseData = combinedInsights.phases[phase];
        if (phaseData.categories && phaseData.categories[category]) {
          combinedInsights.comparison.categories[category][phase] = {
            request_count: phaseData.categories[category].request_count,
            mean_ms: phaseData.categories[category].mean_ms,
            p95_ms: phaseData.categories[category].p95_ms
          };
        }
      }
    }

    console.log('✓ Cross-phase comparison generated');
  }

  // Load and aggregate pricing data from each phase
  console.log('\nAggregating pricing data...');
  for (const phase of phases) {
    const pricingPath = path.join(outputDir, phase, 'pricing', 'pricing.json');
    if (fs.existsSync(pricingPath)) {
      try {
        const phasePricing = JSON.parse(fs.readFileSync(pricingPath, 'utf8'));
        combinedInsights.pricing.phases[phase] = phasePricing.summary;
        console.log(`✓ Loaded pricing from ${phase}: $${phasePricing.summary.total_cost.toFixed(6)}`);
      } catch (error) {
        console.log(`⚠️  Failed to load pricing from ${phase}: ${error.message}`);
      }
    } else {
      console.log(`⚠️  No pricing.json found for phase ${phase}`);
    }
  }

  // Calculate total pricing across all phases
  const pricingPhases = Object.values(combinedInsights.pricing.phases);
  if (pricingPhases.length > 0) {
    const totalCost = pricingPhases.reduce((sum, p) => sum + (p.total_cost || 0), 0);
    const combinedBreakdown = {};

    for (const phaseSummary of pricingPhases) {
      for (const [resource, cost] of Object.entries(phaseSummary.breakdown || {})) {
        combinedBreakdown[resource] = (combinedBreakdown[resource] || 0) + cost;
      }
    }

    combinedInsights.pricing.total = {
      total_cost: totalCost,
      breakdown: combinedBreakdown,
      currency: 'USD'
    };

    console.log(`✓ Total experiment cost: $${totalCost.toFixed(6)}`);
  }

  // Write combined insights to root output directory
  const combinedPath = path.join(outputDir, 'insights.json');
  fs.writeFileSync(combinedPath, JSON.stringify(combinedInsights, null, 2));
  console.log(`\n✓ Combined insights written to: ${combinedPath}`);

  return combinedInsights;
}

/**
 * Prompt user for confirmation before continuing
 * @param {string} message - Message to display to user
 * @returns {Promise<boolean>} - True if user confirms, false otherwise
 */
async function waitForUserConfirmation(message) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
  });

  return new Promise((resolve) => {
    rl.question(`\n${message}\nPress Enter to continue or Ctrl+C to abort... `, () => {
      rl.close();
      resolve(true);
    });
  });
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

  // Hardware configuration
  if (config.architecture === 'faas') {
    console.log(`  Lambda Memory: ${config.memory} MB`);
  } else {
    console.log(`  Fargate CPU: ${config.cpu} units (${config.cpu / 1024} vCPU)`);
    console.log(`  Fargate Memory: ${config.memoryFargate} MB`);
  }

  console.log(`  Workload: ${config.workload}`);
  console.log(`  Run ID: ${config.runId}`);
  console.log(`  Scaling Test: ${config.scaling ? 'enabled' : 'disabled'}`);
  if (config.scaling) {
    console.log(`  Scale Down Wait: ${config.scaleDownWait}s`);
  }
  console.log(`  Output Directory: ${config.outputDir}`);
  console.log(`  Log File: ${logFile}`);

  let buildDir = null;
  let experimentStartTime = null;

  try {
    // Step 0: Validate environment, set hardware config, and install Terraform providers
    validateEnvironment(config.experiment);
    setHardwareConfig(config);
    installTerraformProviders();

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

        await runDestroy(config.experiment, config.architecture, config.auth);
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
      buildDir = await runBuild(config.experiment, config.architecture, config.auth, config.bundleMode, config.algorithm);

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
        datetime: config.runId.split('_').pop() // Extract timestamp from runId
      };
      if (config.architecture !== 'faas') {
        hardwareConfig.cpu_in_vcpu = config.cpu / 1024;
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

      const endpoints = await runDeploy(config.experiment, config.architecture, buildDir, config.auth, config.algorithm);

      // Capture per-service scaling rules from Terraform state into hardware_config.json
      updateHardwareConfigWithScalingRules(config, config.outputDir);

      // Wait for deployment to stabilize
      const isEcsBased = config.architecture === 'monolith' || config.architecture === 'microservices';
      const isEdgeAuth = config.auth === 'edge';
      // CloudFront takes longer to propagate (3-5 min creation + propagation time)
      const stabilizationDelay = isEcsBased ? 180000 : (isEdgeAuth ? 60000 : 5000); // 3 min for ecs, 1 min for edge, 5s for Lambda
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

      // Step 4-7: Run Benchmark Phases
      const isMultiPhase = config.scaling;

      if (isMultiPhase) {
        // Multi-phase benchmark mode
        const enabledPhases = ['baseline'];
        if (config.scaling) enabledPhases.push('scaling');
        logSection('Multi-Phase Benchmark Mode');
        console.log(`Running phases: ${enabledPhases.join(', ')}\n`);

        // Phase 1: Baseline benchmark (always runs, using configured workload)
        const baselineOutputDir = path.join(config.outputDir, 'baseline');
        await runBenchmarkPhase(config, 'Baseline', config.workload, baselineOutputDir);

        // Update hardware_config.json with CPU info from baseline logs
        await updateHardwareConfigWithCpuInfo(path.join(baselineOutputDir, 'logs'), config.outputDir);

        // Phase 2: Scaling benchmark (if enabled)
        if (config.scaling) {
          await waitForScaleDown(config.scaleDownWait);
          const scalingOutputDir = path.join(config.outputDir, 'scaling');
          await runBenchmarkPhase(config, 'Scaling', 'workload-scaling.yml', scalingOutputDir);
        }

        // Write summary of all phases
        const summaryFile = path.join(config.outputDir, 'benchmark_summary.json');
        const summary = {
          phases: enabledPhases,
          baselineWorkload: config.workload,
          architecture: config.architecture,
          auth: config.auth,
          memory: config.memory,
          scaleDownWait: config.scaleDownWait,
          completedAt: new Date().toISOString()
        };
        fs.writeFileSync(summaryFile, JSON.stringify(summary, null, 2));
        console.log(`\nBenchmark summary written to: ${summaryFile}`);

        // Combine insights from all phases into a single insights.json
        combinePhaseInsights(config.outputDir, enabledPhases, config);

      } else {
        // Single-phase benchmark (original behavior - baseline only)
        await resetCognitoUserPool();
        await runBenchmark(config.experiment, config.workload, config.outputDir, config.auth, config.architecture);

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
    }

    // Step 8: Destroy infrastructure if requested
    let destroyFailed = false;
    if (config.destroy) {
      try {
        await runDestroy(config.experiment, config.architecture, config.auth);
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
      if (config.auth === 'edge') {
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
    let cleanupSucceeded = true;
    try {
      // Force destroy Redis containers first to prevent hanging
      console.log('Force destroying Redis containers...');
      try {
        await forceDestroyRedis(config.experiment);
      } catch (redisError) {
        console.warn('Warning: Could not force destroy Redis:', redisError.message);
      }

      // Destroy infrastructure (logs already collected)
      await runDestroy(config.experiment, config.architecture, config.auth);
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
      if (config.auth === 'edge') {
        console.log('Cleaning up Lambda@Edge log groups...');
        try {
          await cleanupAllEdgeLambdaLogs();
        } catch (edgeLogError) {
          console.warn('Warning: Could not cleanup Lambda@Edge logs:', edgeLogError.message);
        }
      }
    } catch (cleanupError) {
      cleanupSucceeded = false;
      console.error('\n⚠️  Infrastructure cleanup failed:', cleanupError.message);
      console.log('Logs and metrics have been collected and analyzed.');
      console.log('You may need to manually destroy the infrastructure or retry later.');
      await waitForUserConfirmation('Infrastructure cleanup failed. Please verify AWS resources are cleaned up before continuing.');
    }

    process.exit(1);
  }
}

main();