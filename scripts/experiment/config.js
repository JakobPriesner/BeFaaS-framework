const fs = require('fs');
const path = require('path');

function printUsage() {
  console.log(`
Usage: node scripts/experiment.js --architecture <arch> --auth <auth> [options]

Required:
  --architecture, -a    Architecture to deploy (faas, microservices, monolith)
  --auth, -u           Authentication strategy (none, service-integrated, service-integrated-manual)

Optional:
  --experiment, -e     Experiment to run (default: webservice)
                       Available: iot, smartFactory, streaming, test, topics, webservice
  --memory             AWS Lambda memory in MB (default: 512, range: 128-10240)
  --keep-infra         Keep infrastructure running after experiment (default: destroy)
  --skip-benchmark     Skip benchmark execution
  --skip-metrics       Skip metrics collection
  --workload           Workload file (default: workload-constant.yml)
  --bundle-mode        FaaS only: 'all' (all functions) or 'minimal' (only needed) (default: minimal)
  --output-dir         Output directory for results (default: ./results/<experiment>/<arch>#<auth>#<mem>#<bundle>#<timestamp>)
  --scaling            Run scaling benchmark after baseline (tests system under increasing load)
  --stress-auth        Run stress-auth benchmark (tests auth endpoints under load)
  --scale-down-wait    Seconds to wait between benchmark phases for scale-down (default: 300)
  --help, -h           Show this help message

Examples:
  # Full experiment run (infra auto-destroyed at the end)
  node scripts/experiment.js -a faas -u none

  # Run with scaling test (baseline + scaling)
  node scripts/experiment.js -a faas -u service-integrated --scaling

  # Run with stress-auth test (baseline + stress-auth)
  node scripts/experiment.js -a faas -u service-integrated --stress-auth

  # Run with both (baseline + scaling + stress-auth)
  node scripts/experiment.js -a faas -u service-integrated --scaling --stress-auth

  # Run with custom Lambda memory configuration
  node scripts/experiment.js -a faas -u none --memory 1024

  # Keep infrastructure running after experiment (for debugging)
  node scripts/experiment.js -a faas -u none --keep-infra
`);
}

function parseArgs(args) {
  const config = {
    experiment: 'webservice',
    architecture: null,
    auth: null,
    destroy: true,  // Default: destroy infrastructure after experiment
    skipBenchmark: false,
    skipMetrics: false,
    workload: 'workload-constant.yml',
    outputDir: null,
    memory: 512,
    bundleMode: 'minimal',
    scaling: false,
    stressAuth: false,
    scaleDownWait: 300 // seconds to wait between benchmark phases for scale-down
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
      case '--destroy':
        config.destroy = true;
        break;
      case '--keep-infra':
        config.destroy = false;
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
      case '--bundle-mode':
        config.bundleMode = args[++i];
        break;
      case '--scaling':
        config.scaling = true;
        break;
      case '--stress-auth':
        config.stressAuth = true;
        break;
      case '--scale-down-wait':
        config.scaleDownWait = parseInt(args[++i]);
        break;
      default:
        console.error(`Unknown argument: ${arg}`);
        printUsage();
        process.exit(1);
    }
  }

  return config;
}

function validateConfig(config) {
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
  const validAuth = ['none', 'service-integrated', 'service-integrated-manual'];
  if (!validAuth.includes(config.auth)) {
    console.error(`Error: Invalid auth strategy. Must be one of: ${validAuth.join(', ')}`);
    process.exit(1);
  }

  // Validate experiment exists
  const projectRoot = path.join(__dirname, '..', '..');
  const experimentsDir = path.join(projectRoot, 'experiments');
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

  // Validate bundleMode (only applies to faas)
  if (config.architecture === 'faas') {
    const validBundleModes = ['all', 'minimal'];
    if (!validBundleModes.includes(config.bundleMode)) {
      console.error(`Error: Invalid bundle mode. Must be one of: ${validBundleModes.join(', ')}`);
      process.exit(1);
    }
  }

  // Set default output directory
  // Format: <architecture>#<auth>#<memory>#<bundle (faas only)>#<timestamp>
  if (!config.outputDir) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const parts = [config.architecture, config.auth, `${config.memory}MB`];
    if (config.architecture === 'faas') {
      parts.push(config.bundleMode);
    }
    parts.push(timestamp);
    config.outputDir = path.join('results', config.experiment, parts.join('#'));
  }

  return config;
}

module.exports = {
  printUsage,
  parseArgs,
  validateConfig
};