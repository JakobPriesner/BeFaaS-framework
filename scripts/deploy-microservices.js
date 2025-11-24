const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

/**
 * Deploy Microservices architecture to AWS ECS using Terraform
 */
async function deployMicroservices(experiment, buildDir) {
  console.log(`Deploying microservices architecture for experiment: ${experiment}`);

  const projectRoot = path.join(__dirname, '..');

  try {
    // Step 1: Setup VPC
    console.log('\nStep 1: Setting up VPC...');
    const vpcDir = path.join(projectRoot, 'infrastructure', 'services', 'vpc');
    if (!fs.existsSync(vpcDir)) {
      throw new Error('VPC infrastructure not found at infrastructure/services/vpc');
    }

    runTerraform(vpcDir, 'init');
    runTerraform(vpcDir, 'apply');

    const vpcOutput = getTerraformOutputJson(vpcDir);
    const vpcId = vpcOutput.vpc_id?.value;
    const privateSubnetIds = vpcOutput.private_subnet_ids?.value || [];
    const publicSubnetIds = vpcOutput.public_subnet_ids?.value || [];

    if (!vpcId) {
      throw new Error('VPC ID not found in Terraform output');
    }

    console.log(`VPC ID: ${vpcId}`);
    console.log(`Private Subnets: ${privateSubnetIds.join(', ')}`);
    console.log(`Public Subnets: ${publicSubnetIds.join(', ')}`);

    // Step 2: Deploy microservices to ECS
    console.log('\nStep 2: Deploying to ECS...');
    const microservicesDir = path.join(projectRoot, 'infrastructure', 'microservices', 'aws');

    if (!fs.existsSync(microservicesDir)) {
      throw new Error('Microservices infrastructure not found at infrastructure/microservices/aws');
    }

    const deploymentId = `${experiment}-${Date.now()}`;
    const buildId = Date.now().toString();

    runTerraform(microservicesDir, 'init');
    runTerraform(microservicesDir, 'apply', {
      vars: {
        deployment_id: deploymentId,
        build_id: buildId,
        vpc_id: vpcId,
        private_subnet_ids: JSON.stringify(privateSubnetIds),
        public_subnet_ids: JSON.stringify(publicSubnetIds),
        aws_region: process.env.AWS_REGION || 'us-east-1'
      }
    });

    const output = getTerraformOutputJson(microservicesDir);
    const albUrl = output.alb_dns_name?.value;

    console.log('\n✓ Microservices deployed to AWS ECS');
    if (albUrl) {
      console.log(`ALB URL: http://${albUrl}`);
      return [`http://${albUrl}/health`];
    }

    return [];

  } catch (error) {
    console.error('\n❌ Microservices deployment failed:', error.message);
    throw error;
  }
}

/**
 * Destroy microservices deployment
 */
async function destroyMicroservices(experiment) {
  console.log(`Destroying microservices deployment for experiment: ${experiment}`);

  const projectRoot = path.join(__dirname, '..');
  const microservicesDir = path.join(projectRoot, 'infrastructure', 'microservices', 'aws');

  if (fs.existsSync(microservicesDir)) {
    console.log('Destroying ECS infrastructure...');
    runTerraform(microservicesDir, 'destroy', { autoApprove: true });
  }

  // Also destroy VPC if needed
  const vpcDir = path.join(projectRoot, 'infrastructure', 'services', 'vpc');
  if (fs.existsSync(vpcDir)) {
    console.log('Destroying VPC...');
    runTerraform(vpcDir, 'destroy', { autoApprove: true });
  }

  console.log('✓ Microservices infrastructure destroyed');
}

// Helper functions

function runTerraform(workingDir, command, options = {}) {
  const { vars = {} } = options;

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

module.exports = { deployMicroservices, destroyMicroservices };