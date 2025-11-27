#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

// Parse command line arguments
const args = process.argv.slice(2);

function printUsage() {
  console.log(`
Usage: node scripts/experiment.js --architecture <arch> --auth <auth> [options]

Required:
  --architecture, -a    Architecture to deploy (faas, microservices, monolith)
  --auth, -u           Authentication strategy (none, service-integrated)

Optional:
  --experiment, -e     Experiment to run (default: webservice)
                       Available: iot, smartFactory, streaming, test, topics, webservice
  --memory             AWS Lambda memory in MB (default: 512, range: 128-10240)
  --build-only         Only build, don't deploy
  --deploy-only        Only deploy (skip build)
  --destroy            Destroy infrastructure after experiment
  --destroy-only       Only destroy infrastructure (skip build, deploy, benchmark)
  --skip-benchmark     Skip benchmark execution
  --skip-metrics       Skip metrics collection
  --workload           Workload file (default: workload-constant.yml)
  --output-dir         Output directory for results (default: ./results/<experiment>/<architecture>/<auth>/<timestamp>)
  --help, -h           Show this help message

Examples:
  # Full experiment run with FaaS architecture and no auth (webservice)
  node scripts/experiment.js -a faas -u none

  # Run with custom Lambda memory configuration
  node scripts/experiment.js -a faas -u none --memory 1024

  # Run smartFactory experiment with microservices
  node scripts/experiment.js -e smartFactory -a microservices -u service-integrated --skip-benchmark

  # Only build monolith architecture for IoT experiment
  node scripts/experiment.js -e iot -a monolith -u none --build-only

  # Run full experiment and destroy infrastructure afterwards
  node scripts/experiment.js -a faas -u none --destroy

  # Only destroy existing infrastructure
  node scripts/experiment.js -a microservices -u service-integrated --destroy-only
`);
}

function parseArgs(args) {
  const config = {
    experiment: 'webservice',
    architecture: null,
    auth: null,
    buildOnly: false,
    deployOnly: false,
    destroy: false,
    destroyOnly: false,
    skipBenchmark: false,
    skipMetrics: false,
    workload: 'workload-constant.yml',
    outputDir: null,
    memory: 512
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];

    switch (arg) {
      case '--help':
      case '-h':
        printUsage();
        process.exit(0);
        break;
      case '--experiment':
      case '-e':
        config.experiment = args[++i];
        break;
      case '--architecture':
      case '-a':
        config.architecture = args[++i];
        break;
      case '--auth':
      case '-u':
        config.auth = args[++i];
        break;
      case '--build-only':
        config.buildOnly = true;
        break;
      case '--deploy-only':
        config.deployOnly = true;
        break;
      case '--destroy':
        config.destroy = true;
        break;
      case '--destroy-only':
        config.destroyOnly = true;
        break;
      case '--skip-benchmark':
        config.skipBenchmark = true;
        break;
      case '--skip-metrics':
        config.skipMetrics = true;
        break;
      case '--workload':
        config.workload = args[++i];
        break;
      case '--output-dir':
        config.outputDir = args[++i];
        break;
      case '--memory':
        config.memory = parseInt(args[++i]);
        break;
      default:
        console.error(`Unknown argument: ${arg}`);
        printUsage();
        process.exit(1);
    }
  }

  // Validate required arguments
  if (!config.architecture) {
    console.error('Error: --architecture is required');
    printUsage();
    process.exit(1);
  }

  if (!config.auth) {
    console.error('Error: --auth is required');
    printUsage();
    process.exit(1);
  }

  // Validate architecture
  const validArchitectures = ['faas', 'microservices', 'monolith'];
  if (!validArchitectures.includes(config.architecture)) {
    console.error(`Error: Invalid architecture. Must be one of: ${validArchitectures.join(', ')}`);
    process.exit(1);
  }

  // Validate auth
  const validAuth = ['none', 'service-integrated'];
  if (!validAuth.includes(config.auth)) {
    console.error(`Error: Invalid auth strategy. Must be one of: ${validAuth.join(', ')}`);
    process.exit(1);
  }

  // Validate experiment exists
  const experimentsDir = path.join(__dirname, '..', 'experiments');
  const validExperiments = fs.readdirSync(experimentsDir).filter(file => {
    const fullPath = path.join(experimentsDir, file);
    return fs.statSync(fullPath).isDirectory();
  });

  if (!validExperiments.includes(config.experiment)) {
    console.error(`Error: Invalid experiment. Must be one of: ${validExperiments.join(', ')}`);
    process.exit(1);
  }

  // Validate memory if provided
  if (config.memory) {
    if (isNaN(config.memory) || config.memory < 128 || config.memory > 10240) {
      console.error('Error: Memory must be between 128 MB and 10240 MB');
      process.exit(1);
    }
  }

  // Set default output directory
  if (!config.outputDir) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    config.outputDir = path.join('results', config.experiment, `${config.architecture}-${config.auth}-${timestamp}`);
  }

  return config;
}

function logSection(title) {
  console.log('\n' + '='.repeat(60));
  console.log(`  ${title}`);
  console.log('='.repeat(60) + '\n');
}

function validateEnvironment(experiment) {
  logSection('Validating Environment');

  const projectRoot = path.join(__dirname, '..');
  const experimentJsonPath = path.join(projectRoot, 'experiments', experiment, 'experiment.json');

  if (!fs.existsSync(experimentJsonPath)) {
    console.log('⚠ experiment.json not found, skipping provider validation');
    return;
  }

  const experimentConfig = JSON.parse(fs.readFileSync(experimentJsonPath, 'utf8'));
  const providers = getProvidersFromConfig(experimentConfig);

  console.log(`Checking environment for providers: ${providers.join(', ')}`);

  // Check AWS
  if (providers.includes('aws')) {
    if (!process.env.AWS_REGION && !process.env.AWS_DEFAULT_REGION) {
      console.error('❌ Error: AWS_REGION environment variable should be set');
      process.exit(1);
    }
    console.log(`✓ AWS_REGION: ${process.env.AWS_REGION || process.env.AWS_DEFAULT_REGION}`);
  }

  // Check Google Cloud
  if (providers.includes('google')) {
    if (!process.env.GOOGLE_REGION) {
      console.error('❌ Error: GOOGLE_REGION environment variable should be set');
      process.exit(1);
    }
    if (!process.env.GOOGLE_APPLICATION_CREDENTIALS) {
      console.error('❌ Error: GOOGLE_APPLICATION_CREDENTIALS environment variable should be set');
      process.exit(1);
    }
    if (!process.env.GOOGLE_PROJECT) {
      console.error('❌ Error: GOOGLE_PROJECT environment variable should be set');
      process.exit(1);
    }
    console.log(`✓ GOOGLE_REGION: ${process.env.GOOGLE_REGION}`);
    console.log(`✓ GOOGLE_PROJECT: ${process.env.GOOGLE_PROJECT}`);
  }

  // Set Terraform variables for all providers
  if (providers.includes('tinyfaas')) {
    process.env.TF_VAR_TINYFAAS_ADDRESS = process.env.TINYFAAS_ADDRESS || '';
    process.env.TF_VAR_TINYFAAS_MPORT = process.env.TINYFAAS_MPORT || '';
    process.env.TF_VAR_TINYFAAS_FPORT = process.env.TINYFAAS_FPORT || '';
    if (process.env.TINYFAAS_ADDRESS) {
      console.log(`✓ TinyFaaS configured: ${process.env.TINYFAAS_ADDRESS}`);
    }
  }

  if (providers.includes('openfaas')) {
    process.env.TF_VAR_OPENFAAS_GATEWAY = process.env.OPENFAAS_GATEWAY || '';
    process.env.TF_VAR_OPENFAAS_USER = 'admin';
    process.env.TF_VAR_OPENFAAS_TOKEN = process.env.OPENFAAS_TOKEN || '';
    if (process.env.OPENFAAS_GATEWAY) {
      console.log(`✓ OpenFaaS configured: ${process.env.OPENFAAS_GATEWAY}`);
    }
  }

  if (providers.includes('openwhisk')) {
    process.env.TF_VAR_OPENWHISK_EXTERNAL = process.env.OPENWHISK_EXTERNAL || '';
    if (process.env.OPENWHISK_EXTERNAL) {
      console.log(`✓ OpenWhisk configured: ${process.env.OPENWHISK_EXTERNAL}`);
    }
  }

  // Detect and set Docker Hub user
  try {
    const dockerInfo = execSync('docker info 2>/dev/null', { encoding: 'utf8' });
    const match = dockerInfo.match(/Username:\s+(.+)/);
    if (match) {
      process.env.TF_VAR_DOCKERHUB_USER = match[1].trim();
      console.log(`✓ Docker Hub user: ${process.env.TF_VAR_DOCKERHUB_USER}`);
    }
  } catch (error) {
    console.log('⚠ Could not detect Docker Hub user');
  }

  // Set Terraform config file
  process.env.TF_CLI_CONFIG_FILE = '/experiments/dev.tfrc';

  console.log('✓ Environment validation completed');
}

function setHardwareConfig(config) {
  // Set Lambda memory configuration for AWS
  if (config.memory) {
    process.env.TF_VAR_memory_size = config.memory.toString();
    console.log(`✓ Lambda memory configured: ${config.memory} MB`);
  }
}

function getProvidersFromConfig(config) {
  const providers = new Set();
  if (config.program && config.program.functions) {
    for (const func of Object.values(config.program.functions)) {
      if (func.provider) {
        providers.add(func.provider);
      }
    }
  }
  return Array.from(providers);
}

function installTerraformProviders() {
  logSection('Installing Terraform Providers');

  const projectRoot = path.join(__dirname, '..');
  const installScript = path.join(projectRoot, 'scripts', 'install-provider.sh');

  if (!fs.existsSync(installScript)) {
    console.log('⚠ install-provider.sh not found, skipping...');
    return;
  }

  try {
    console.log('Installing custom Terraform providers...');
    execSync(installScript, {
      cwd: projectRoot,
      stdio: 'inherit',
      shell: '/bin/bash'
    });
    console.log('✓ Terraform providers installed');
  } catch (error) {
    console.error('❌ Failed to install Terraform providers:', error.message);
    throw error;
  }
}

async function runBuild(experiment, architecture, auth) {
  logSection(`Building ${experiment}/${architecture} architecture with ${auth} auth`);

  const buildScript = path.join(__dirname, '..', 'experiments', experiment, 'architectures', architecture, 'build.js');

  if (!fs.existsSync(buildScript)) {
    throw new Error(`Build script not found: ${buildScript}`);
  }

  // Import and run the build script
  const build = require(buildScript);
  const tmpDir = path.join(__dirname, '..', 'experiments', experiment, 'architectures', architecture, '_build');

  // Clean the build directory
  if (fs.existsSync(tmpDir)) {
    fs.rmSync(tmpDir, { recursive: true });
  }

  // Run architecture-specific build
  await build(tmpDir, auth);

  console.log(`✓ Build completed successfully`);
  return tmpDir;
}

async function runDeploy(experiment, architecture, buildDir) {
  logSection(`Deploying ${experiment}/${architecture} architecture`);

  try {
    let endpoints = [];

    switch (architecture) {
      case 'faas': {
        const { deployFaaS } = require('./deploy-faas');
        endpoints = await deployFaaS(experiment, buildDir);
        break;
      }

      case 'microservices': {
        const { deployMicroservices } = require('./deploy-microservices');
        endpoints = await deployMicroservices(experiment, buildDir);
        break;
      }

      case 'monolith': {
        const { deployMonolith } = require('./deploy-monolith');
        endpoints = await deployMonolith(experiment, buildDir);
        break;
      }

      default:
        throw new Error(`Unknown architecture: ${architecture}`);
    }

    console.log('✓ Deployment completed');
    return endpoints;

  } catch (error) {
    console.error('✗ Deployment failed:', error.message);
    throw error;
  }
}

async function runBenchmark(experiment, workload, outputDir) {
  logSection('Running Benchmark');

  const experimentJsonPath = path.join(__dirname, '..', 'experiments', experiment, 'experiment.json');

  if (!fs.existsSync(experimentJsonPath)) {
    throw new Error(`experiment.json not found: ${experimentJsonPath}`);
  }

  const experimentConfig = JSON.parse(fs.readFileSync(experimentJsonPath, 'utf8'));

  // Check if workload service is configured
  if (!experimentConfig.services || !experimentConfig.services.workload) {
    console.log('No workload service configured, skipping benchmark');
    return;
  }

  const workloadConfigName = experimentConfig.services.workload.config;
  if (!workloadConfigName) {
    throw new Error('Workload config not defined (services.workload.config)');
  }

  const workloadPath = path.join(__dirname, '..', 'experiments', experiment, workloadConfigName);
  if (!fs.existsSync(workloadPath)) {
    throw new Error(`Workload file not found: ${workloadPath}`);
  }

  // Create output directory
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  console.log(`Using workload: ${workloadConfigName}`);
  console.log(`Output directory: ${outputDir}`);

  // Run the workload.sh script and capture logs
  const logFile = path.join(outputDir, 'workload.log');
  const workloadScript = path.join(__dirname, 'workload.sh');
  const projectRoot = path.join(__dirname, '..');

  return new Promise((resolve, reject) => {
    console.log('Running workload script...');

    const { spawn } = require('child_process');
    const workloadLogStream = fs.createWriteStream(logFile);

    // Use spawn with inherit for stdin/stdout/stderr so output appears in real-time
    // and goes through our logging override
    const child = spawn(workloadScript, [experiment], {
      cwd: projectRoot,
      stdio: ['inherit', 'pipe', 'pipe'],
      shell: '/bin/bash'
    });

    // Pipe output to both console and workload.log
    child.stdout.on('data', (data) => {
      process.stdout.write(data);
      workloadLogStream.write(data);
    });

    child.stderr.on('data', (data) => {
      process.stderr.write(data);
      workloadLogStream.write(data);
    });

    child.on('close', (code) => {
      workloadLogStream.end();

      if (code !== 0) {
        reject(new Error(`Workload script exited with code ${code}`));
      } else {
        console.log('✓ Benchmark completed');
        resolve();
      }
    });

    child.on('error', (error) => {
      workloadLogStream.end();
      reject(new Error(`Failed to start workload script: ${error.message}`));
    });
  });
}

async function collectMetrics(experiment, outputDir, experimentStartTime) {
  logSection('Collecting Logs and Metrics');

  const logsScript = path.join(__dirname, 'logs.sh');
  const experimentJsonPath = path.join(__dirname, '..', 'experiments', experiment, 'experiment.json');

  if (!fs.existsSync(experimentJsonPath)) {
    console.log('No experiment.json found, skipping logs collection');
    return;
  }

  try {
    console.log('Running logs collection script...');

    const projectRoot = path.join(__dirname, '..');

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
      const { spawn } = require('child_process');
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
    const logsDir = path.join(__dirname, '..', 'logs', experiment);
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

  const projectRoot = path.join(__dirname, '..');
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
    const generatePlotsScript = path.join(__dirname, 'generate_plots.py');

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
    const validateScript = path.join(__dirname, 'validate_responses.py');
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
    const analyzeErrorsScript = path.join(__dirname, 'analyze_errors.py');
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

async function checkHealth(endpoints, maxRetries = 10, retryDelay = 3000) {
  if (!endpoints || endpoints.length === 0) {
    console.log('No health check endpoints configured, skipping health check');
    return true;
  }

  logSection('Health Check');
  console.log(`Checking ${endpoints.length} endpoint(s)...`);

  const http = require('http');
  const https = require('https');

  async function checkEndpoint(url) {
    return new Promise((resolve) => {
      const client = url.startsWith('https') ? https : http;
      const req = client.get(url, { timeout: 5000 }, (res) => {
        resolve(res.statusCode >= 200 && res.statusCode < 300);
      });

      req.on('error', () => resolve(false));
      req.on('timeout', () => {
        req.destroy();
        resolve(false);
      });
    });
  }

  const results = {};
  for (const endpoint of endpoints) {
    results[endpoint] = false;
  }

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    console.log(`\nAttempt ${attempt}/${maxRetries}`);

    for (const endpoint of endpoints) {
      if (results[endpoint]) {
        console.log(`  ✓ ${endpoint} (already healthy)`);
        continue;
      }

      const isHealthy = await checkEndpoint(endpoint);
      results[endpoint] = isHealthy;

      if (isHealthy) {
        console.log(`  ✓ ${endpoint}`);
      } else {
        console.log(`  ✗ ${endpoint}`);
      }
    }

    // Check if all endpoints are healthy
    const allHealthy = Object.values(results).every(v => v === true);
    if (allHealthy) {
      console.log('\n✓ All services are healthy!');
      return true;
    }

    // Wait before next retry (except on last attempt)
    if (attempt < maxRetries) {
      console.log(`\nWaiting ${retryDelay / 1000}s before next check...`);
      await new Promise(resolve => setTimeout(resolve, retryDelay));
    }
  }

  // Final check
  const unhealthyEndpoints = Object.entries(results)
    .filter(([_, healthy]) => !healthy)
    .map(([endpoint]) => endpoint);

  if (unhealthyEndpoints.length > 0) {
    console.error('\n❌ Some services failed health check:');
    unhealthyEndpoints.forEach(endpoint => console.error(`  - ${endpoint}`));
    return false;
  }

  return true;
}

async function runDestroy(experiment, architecture) {
  logSection(`Destroying ${experiment}/${architecture} infrastructure`);

  try {
    switch (architecture) {
      case 'faas': {
        const { destroyFaaS } = require('./deploy-faas');
        await destroyFaaS(experiment);
        break;
      }

      case 'microservices': {
        const { destroyMicroservices } = require('./deploy-microservices');
        await destroyMicroservices(experiment);
        break;
      }

      case 'monolith': {
        const { destroyMonolith } = require('./deploy-monolith');
        await destroyMonolith(experiment);
        break;
      }

      default:
        throw new Error(`Unknown architecture: ${architecture}`);
    }

    console.log('✓ Infrastructure destroyed successfully');

  } catch (error) {
    console.error('✗ Destroy failed:', error.message);
    throw error;
  }
}

function cleanupBuildArtifacts(experiment, architecture) {
  logSection('Cleaning up build artifacts');

  const projectRoot = path.join(__dirname, '..');
  const pathsToClean = [
    // Architecture-specific build directory
    path.join(projectRoot, 'experiments', experiment, 'architectures', architecture, '_build'),
    // Shared functions build directory
    path.join(projectRoot, 'experiments', experiment, 'functions', '_build'),
    // Results directory for this architecture
    path.join(projectRoot, 'results', experiment, `${architecture}-*`)
  ];

  for (const cleanPath of pathsToClean) {
    // Handle glob patterns for results directory
    if (cleanPath.includes('*')) {
      const dirPath = path.dirname(cleanPath);
      const pattern = path.basename(cleanPath);
      if (fs.existsSync(dirPath)) {
        const entries = fs.readdirSync(dirPath);
        for (const entry of entries) {
          if (entry.match(new RegExp(pattern.replace('*', '.*')))) {
            const fullPath = path.join(dirPath, entry);
            console.log(`  Removing: ${fullPath}`);
            if (fs.existsSync(fullPath)) {
              fs.rmSync(fullPath, { recursive: true, force: true });
            }
          }
        }
      }
    } else {
      if (fs.existsSync(cleanPath)) {
        console.log(`  Removing: ${cleanPath}`);
        fs.rmSync(cleanPath, { recursive: true, force: true });
      }
    }
  }

  console.log('✓ Cleanup completed');
}

async function main() {
  const config = parseArgs(args);

  // Create output directory early
  if (!fs.existsSync(config.outputDir)) {
    fs.mkdirSync(config.outputDir, { recursive: true });
  }

  // Setup logging to file
  const logFile = path.join(config.outputDir, 'experiment.log');
  const logStream = fs.createWriteStream(logFile, { flags: 'a' });

  // Capture stdout and stderr
  const originalStdoutWrite = process.stdout.write.bind(process.stdout);
  const originalStderrWrite = process.stderr.write.bind(process.stderr);

  process.stdout.write = (chunk, encoding, callback) => {
    logStream.write(chunk, encoding);
    return originalStdoutWrite(chunk, encoding, callback);
  };

  process.stderr.write = (chunk, encoding, callback) => {
    logStream.write(chunk, encoding);
    return originalStderrWrite(chunk, encoding, callback);
  };

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
      // Cleanup build artifacts
      cleanupBuildArtifacts(config.experiment, config.architecture);

      // Destroy existing infrastructure
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

    // Step 2: Deploy
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
      console.log('\nWaiting for deployment to stabilize...');
      await new Promise(resolve => setTimeout(resolve, 5000));

      // Health check
      const isHealthy = await checkHealth(endpoints);
      if (!isHealthy) {
        throw new Error('Deployment failed health check');
      }
    }

    // Step 3: Run Benchmark
    if (!config.buildOnly && !config.skipBenchmark) {
      await runBenchmark(config.experiment, config.workload, config.outputDir);
    }

    // Step 4: Collect Metrics
    if (!config.buildOnly && !config.skipMetrics) {
      await collectMetrics(config.experiment, config.outputDir, experimentStartTime);
    }

    // Step 5: Analyze Results
    if (!config.buildOnly && !config.skipBenchmark) {
      await analyzeResults(config.experiment, config.outputDir);
    }

    // Step 6: Destroy infrastructure if requested
    if (config.destroy && !config.buildOnly) {
      await runDestroy(config.experiment, config.architecture);
      cleanupBuildArtifacts(config.experiment, config.architecture);
    }

    logSection('Experiment Complete');
    console.log(`Results saved to: ${config.outputDir}`);
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