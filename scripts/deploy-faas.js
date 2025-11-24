const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { createZip, installDependencies } = require('../experiments/webservice/architectures/shared/buildUtils');

/**
 * Deploy FaaS architecture using Terraform
 */
async function deployFaaS(experiment, buildDir) {
  console.log(`Deploying FaaS architecture for experiment: ${experiment}`);

  const projectRoot = path.join(__dirname, '..');

  // Check if experiment.json exists
  const experimentJsonPath = path.join(projectRoot, 'experiments', experiment, 'experiment.json');
  if (!fs.existsSync(experimentJsonPath)) {
    throw new Error(`experiment.json not found at ${experimentJsonPath}`);
  }

  const experimentConfig = JSON.parse(fs.readFileSync(experimentJsonPath, 'utf8'));
  const providers = getProvidersFromConfig(experimentConfig);

  console.log(`Found providers: ${providers.join(', ')}`);

  // Generate build timestamp
  const buildTimestamp = new Date().toISOString();
  const buildTimestampFile = path.join(projectRoot, '.build_timestamp');
  fs.writeFileSync(buildTimestampFile, buildTimestamp);

  const endpoints = [];

  try {
    // Step 0: Prepare function zip files
    console.log('\nStep 0: Preparing function zip files...');
    prepareFunctionZips(projectRoot, experiment, buildDir, experimentConfig);

    // Step 1: Deploy experiment infrastructure
    console.log('\nStep 1: Deploying experiment infrastructure...');
    const experimentInfraDir = path.join(projectRoot, 'infrastructure', 'experiment');
    runTerraform(experimentInfraDir, 'init');
    runTerraform(experimentInfraDir, 'apply', {
      vars: {
        experiment: experiment,
        build_timestamp: buildTimestamp
      }
    });

    const deploymentId = getTerraformOutput(experimentInfraDir, 'deployment_id');
    console.log(`Deployment ID: ${deploymentId}`);

    // Step 2: Initialize provider endpoints
    console.log('\nStep 2: Initializing provider endpoints...');
    const states = {};
    for (const provider of providers) {
      const endpointDir = path.join(projectRoot, 'infrastructure', provider, 'endpoint');
      if (fs.existsSync(endpointDir)) {
        console.log(`Initializing ${provider} endpoint...`);
        runTerraform(endpointDir, 'init');
        runTerraform(endpointDir, 'apply');

        const output = getTerraformOutputJson(endpointDir);
        Object.assign(states, output);
      }
    }

    // Step 3: Setup services (if any)
    if (experimentConfig.services && Object.keys(experimentConfig.services).length > 0) {
      console.log('\nStep 3: Setting up services...');

      // Setup VPC
      const vpcDir = path.join(projectRoot, 'infrastructure', 'services', 'vpc');
      if (fs.existsSync(vpcDir)) {
        console.log('Setting up VPC...');
        runTerraform(vpcDir, 'init');
        runTerraform(vpcDir, 'apply');
      }

      // Setup each service
      for (const service of Object.keys(experimentConfig.services)) {
        if (service === 'workload') continue;

        const serviceDir = path.join(projectRoot, 'infrastructure', 'services', service);
        if (fs.existsSync(serviceDir)) {
          console.log(`Starting service ${service}...`);
          runTerraform(serviceDir, 'init');
          runTerraform(serviceDir, 'apply');

          const output = getTerraformOutputJson(serviceDir);
          Object.assign(states, output);
        }
      }
    }

    // Step 4: Prepare function environment variables
    const fnEnv = extractEndpoints(states);
    console.log('\nFunction environment variables:', fnEnv);

    // Step 5: Deploy functions to providers
    console.log('\nStep 4: Deploying functions to providers...');
    for (const provider of providers) {
      const providerDir = path.join(projectRoot, 'infrastructure', provider);
      if (fs.existsSync(providerDir) && !providerDir.includes('endpoint')) {
        console.log(`Deploying to ${provider}...`);

        // Set environment variable for function env
        process.env.TF_VAR_fn_env = JSON.stringify(fnEnv);

        runTerraform(providerDir, 'init');
        runTerraform(providerDir, 'apply');

        // Get provider endpoints
        const providerOutput = getTerraformOutputJson(providerDir);
        for (const [key, value] of Object.entries(providerOutput)) {
          if (key.includes('endpoint') || key.includes('url')) {
            const endpoint = value.value || value;
            if (endpoint) {
              endpoints.push(endpoint);
            }
          }
        }
      }
    }

    console.log('\n✓ FaaS deployment completed successfully');
    console.log(`Deployed ${endpoints.length} endpoints`);

    return endpoints;

  } catch (error) {
    console.error('\n❌ FaaS deployment failed:', error.message);
    throw error;
  }
}

/**
 * Destroy FaaS infrastructure
 */
async function destroyFaaS(experiment) {
  console.log(`Destroying FaaS infrastructure for experiment: ${experiment}`);

  const projectRoot = path.join(__dirname, '..');
  const experimentJsonPath = path.join(projectRoot, 'experiments', experiment, 'experiment.json');

  if (!fs.existsSync(experimentJsonPath)) {
    console.log('No experiment.json found, skipping...');
    return;
  }

  const experimentConfig = JSON.parse(fs.readFileSync(experimentJsonPath, 'utf8'));
  const providers = getProvidersFromConfig(experimentConfig);

  // Set empty fn_env for destroy operations
  process.env.TF_VAR_fn_env = JSON.stringify({});

  // Destroy in reverse order
  for (const provider of providers) {
    const providerDir = path.join(projectRoot, 'infrastructure', provider);
    if (fs.existsSync(providerDir)) {
      console.log(`Destroying ${provider}...`);
      try {
        runTerraform(providerDir, 'destroy', { autoApprove: true });
      } catch (error) {
        console.warn(`Warning: Failed to destroy ${provider}:`, error.message);
      }
    }
  }

  console.log('✓ FaaS infrastructure destroyed');
}

// Helper functions

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

function extractEndpoints(states) {
  const endpoints = {};
  for (const [key, value] of Object.entries(states)) {
    if (key.endsWith('ENDPOINT') || key.endsWith('_endpoint')) {
      endpoints[key] = value.value || value;
    }
  }
  return endpoints;
}

function runTerraform(workingDir, command, options = {}) {
  const { vars = {}, autoApprove = false } = options;

  let cmd = `terraform ${command}`;

  // Add variables
  for (const [key, value] of Object.entries(vars)) {
    cmd += ` -var="${key}=${value}"`;
  }

  // Add auto-approve for apply/destroy
  if (command === 'apply' || command === 'destroy') {
    cmd += ' -auto-approve';
  }

  console.log(`  → ${cmd}`);
  execSync(cmd, {
    cwd: workingDir,
    stdio: 'inherit'
  });
}

function getTerraformOutput(workingDir, outputName) {
  const cmd = `terraform output -raw ${outputName}`;
  const result = execSync(cmd, {
    cwd: workingDir,
    encoding: 'utf8'
  });
  return result.trim();
}

function getTerraformOutputJson(workingDir) {
  try {
    const cmd = 'terraform output -json';
    const result = execSync(cmd, {
      cwd: workingDir,
      encoding: 'utf8'
    });
    return JSON.parse(result);
  } catch (error) {
    console.warn(`Warning: Could not get Terraform output from ${workingDir}`);
    return {};
  }
}

/**
 * Prepare function zip files from the built function directories
 * This creates zip files in the location expected by Terraform
 */
function prepareFunctionZips(projectRoot, experiment, buildDir, experimentConfig) {
  // buildDir is the architecture-specific build directory (e.g., experiments/webservice/architectures/faas/_build)
  // We need to create zips in experiments/webservice/functions/_build/

  const targetBuildDir = path.join(projectRoot, 'experiments', experiment, 'functions', '_build');

  // Create the target build directory
  if (!fs.existsSync(targetBuildDir)) {
    fs.mkdirSync(targetBuildDir, { recursive: true });
  }

  // Get all function directories from the architecture-specific build
  if (!fs.existsSync(buildDir)) {
    throw new Error(`Build directory not found: ${buildDir}. Did you run the build step?`);
  }

  const functionDirs = fs.readdirSync(buildDir).filter(file => {
    const fullPath = path.join(buildDir, file);
    return fs.statSync(fullPath).isDirectory();
  });

  console.log(`Found ${functionDirs.length} functions to package: ${functionDirs.join(', ')}`);

  // Install dependencies and create zip for each function
  for (const functionName of functionDirs) {
    const functionDir = path.join(buildDir, functionName);
    const zipPath = path.join(targetBuildDir, `${functionName}.zip`);

    console.log(`\nProcessing function: ${functionName}`);

    // Install dependencies if package.json exists
    if (fs.existsSync(path.join(functionDir, 'package.json'))) {
      try {
        installDependencies(functionDir, true);
      } catch (error) {
        console.warn(`  Warning: Failed to install dependencies for ${functionName}: ${error.message}`);
      }
    }

    // Create zip file
    createZip(functionDir, zipPath);
  }

  console.log(`\n✓ All function zips created in ${targetBuildDir}`);
}

module.exports = { deployFaaS, destroyFaaS };