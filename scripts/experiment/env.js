const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { logSection } = require('./utils');

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

function validateEnvironment(experiment) {
  logSection('Validating Environment');

  const projectRoot = path.join(__dirname, '..', '..');
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

  // Detect and set Docker Hub user (with timeout to prevent hanging)
  try {
    const dockerInfo = execSync('docker info 2>/dev/null', {
      encoding: 'utf8',
      timeout: 10000  // 10 second timeout
    });
    const match = dockerInfo.match(/Username:\s+(.+)/);
    if (match) {
      process.env.TF_VAR_DOCKERHUB_USER = match[1].trim();
      console.log(`✓ Docker Hub user: ${process.env.TF_VAR_DOCKERHUB_USER}`);
    }
  } catch (error) {
    if (error.killed) {
      console.log('⚠ Docker info timed out - Docker may be starting up');
    } else {
      console.log('⚠ Could not detect Docker Hub user');
    }
  }

  // Set Terraform config file (only if running in Docker container)
  const tfConfigPath = '/experiments/dev.tfrc';
  if (fs.existsSync(tfConfigPath)) {
    process.env.TF_CLI_CONFIG_FILE = tfConfigPath;
  }

  console.log('✓ Environment validation completed');
}

function setHardwareConfig(config) {
  logSection('Configuring Hardware');

  // Set Lambda memory configuration for FaaS
  if (config.architecture === 'faas' && config.memory) {
    process.env.TF_VAR_memory_size = config.memory.toString();
    console.log(`✓ Lambda memory configured: ${config.memory} MB`);
  }

  // Set Fargate CPU/Memory configuration for Monolith and Microservices
  if (config.architecture === 'monolith' || config.architecture === 'microservices') {
    if (config.cpu) {
      process.env.TF_VAR_cpu = config.cpu.toString();
      const vCPU = config.cpu / 1024;
      console.log(`✓ Fargate CPU configured: ${config.cpu} units (${vCPU} vCPU)`);
    }
    if (config.memoryFargate) {
      process.env.TF_VAR_memory = config.memoryFargate.toString();
      console.log(`✓ Fargate memory configured: ${config.memoryFargate} MB`);
    }
  }
}

function installTerraformProviders() {
  logSection('Installing Terraform Providers');

  const projectRoot = path.join(__dirname, '..', '..');
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

module.exports = {
  getProvidersFromConfig,
  validateEnvironment,
  setHardwareConfig,
  installTerraformProviders
};