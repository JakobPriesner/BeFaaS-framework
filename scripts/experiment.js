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
  deleteLocalResults,
  setupLogging
} = require('./experiment/utils');

/**
 * Run a single benchmark phase including benchmark execution, metrics collection, and analysis
 * @param {Object} config - Experiment configuration
 * @param {string} phaseName - Name of the benchmark phase (e.g., 'baseline', 'stress-auth')
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
  await runBenchmark(config.experiment, workload, phaseOutputDir);

  // Collect metrics
  if (!config.skipMetrics) {
    await collectMetrics(config.experiment, phaseOutputDir, phaseStartTime);
  }

  // Analyze results
  await analyzeResults(config.experiment, phaseOutputDir);

  return phaseStartTime;
}

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

  // Write combined insights to root output directory
  const combinedPath = path.join(outputDir, 'insights.json');
  fs.writeFileSync(combinedPath, JSON.stringify(combinedInsights, null, 2));
  console.log(`\n✓ Combined insights written to: ${combinedPath}`);

  return combinedInsights;
}

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
  console.log(`  Scaling Test: ${config.scaling ? 'enabled' : 'disabled'}`);
  console.log(`  Stress Auth Test: ${config.stressAuth ? 'enabled' : 'disabled'}`);
  if (config.scaling || config.stressAuth) {
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

    // Step 1: Cleanup and destroy existing infrastructure
    cleanupBuildArtifacts(config.experiment, config.architecture);

    try {
      await runDestroy(config.experiment, config.architecture);
    } catch (error) {
      console.log('No existing infrastructure to destroy or destroy failed:', error.message);
    }

    // Step 2: Build
    buildDir = await runBuild(config.experiment, config.architecture, config.auth, config.bundleMode);

    // Step 3: Deploy
    // Record experiment start time (in milliseconds for AWS CloudWatch)
    // Subtract 1 minute buffer to ensure we capture initialization logs
    experimentStartTime = Date.now() - 60000;

    // Write timestamp to file for reference
    const timestampFile = path.join(config.outputDir, 'experiment_start_time.txt');
    fs.writeFileSync(timestampFile, `${experimentStartTime}\n${new Date(experimentStartTime).toISOString()}`);
    console.log(`Experiment start time recorded: ${new Date(experimentStartTime).toISOString()}`);

    const endpoints = await runDeploy(config.experiment, config.architecture, buildDir);

    // Wait for deployment to stabilize
    const isEcsBased = config.architecture === 'monolith' || config.architecture === 'microservices';
    const stabilizationDelay = isEcsBased ? 180000 : 5000; // 3 min for ecs, 5s for Lambda
    const healthCheckRetries = 120;
    const healthCheckDelay = isEcsBased ? 30000 : 3000; // 30s for ecs, 3s for Lambda

    console.log(`\nWaiting for deployment to stabilize (${stabilizationDelay / 1000}s)...`);
    await new Promise(resolve => setTimeout(resolve, stabilizationDelay));

    // Health check
    const isHealthy = await checkHealth(endpoints, healthCheckRetries, healthCheckDelay);
    if (!isHealthy) {
      throw new Error('Deployment failed health check');
    }

    // Step 4-7: Run Benchmark Phases
    if (!config.skipBenchmark) {
      const isMultiPhase = config.scaling || config.stressAuth;

      if (isMultiPhase) {
        // Multi-phase benchmark mode
        const enabledPhases = ['baseline'];
        if (config.scaling) enabledPhases.push('scaling');
        if (config.stressAuth) enabledPhases.push('stress-auth');

        logSection('Multi-Phase Benchmark Mode');
        console.log(`Running phases: ${enabledPhases.join(', ')}\n`);

        // Phase 1: Baseline benchmark (always runs, using configured workload)
        const baselineOutputDir = path.join(config.outputDir, 'baseline');
        await runBenchmarkPhase(config, 'Baseline', config.workload, baselineOutputDir);

        // Phase 2: Scaling benchmark (if enabled)
        if (config.scaling) {
          await waitForScaleDown(config.scaleDownWait);
          const scalingOutputDir = path.join(config.outputDir, 'scaling');
          await runBenchmarkPhase(config, 'Scaling', 'workload-scaling.yml', scalingOutputDir);
        }

        // Phase 3: Stress Auth benchmark (if enabled)
        if (config.stressAuth) {
          await waitForScaleDown(config.scaleDownWait);
          const stressAuthOutputDir = path.join(config.outputDir, 'stress-auth');
          await runBenchmarkPhase(config, 'Stress Auth', 'workload-stress-auth.yml', stressAuthOutputDir);
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
        await runBenchmark(config.experiment, config.workload, config.outputDir);

        if (!config.skipMetrics) {
          await collectMetrics(config.experiment, config.outputDir, experimentStartTime);
        }

        await analyzeResults(config.experiment, config.outputDir);
      }
    }

    // Step 8: Destroy infrastructure if requested
    if (config.destroy) {
      await runDestroy(config.experiment, config.architecture);
      cleanupBuildArtifacts(config.experiment, config.architecture);
    }

    // Step 9: Upload results to S3
    const uploadSuccess = await uploadResultsToS3(
      config.outputDir,
      config.experiment,
      config.architecture,
      config.auth
    );

    // Step 10: Delete local results after successful upload
    if (uploadSuccess) {
      deleteLocalResults(config.outputDir);
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