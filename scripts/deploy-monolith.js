const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

/**
 * Deploy Monolith architecture to AWS ECS using Terraform
 */
async function deployMonolith(experiment, buildDir) {
  console.log(`Deploying monolith architecture for experiment: ${experiment}`);

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

    // Step 2: Deploy monolith to ECS
    console.log('\nStep 2: Deploying monolith to ECS...');

    // Check if there's a specific monolith infrastructure directory
    let monolithDir = path.join(projectRoot, 'infrastructure', 'monolith', 'aws');

    // If not, we can use a simple ECS deployment
    if (!fs.existsSync(monolithDir)) {
      console.log('Note: Using generic ECS deployment for monolith');
      // Could create a minimal terraform config here or use existing infrastructure
      throw new Error('Monolith infrastructure not found. Please create infrastructure/monolith/aws');
    }

    const deploymentId = `${experiment}-monolith-${Date.now()}`;
    const buildId = Date.now().toString();

    runTerraform(monolithDir, 'init');
    runTerraform(monolithDir, 'apply', {
      vars: {
        deployment_id: deploymentId,
        build_id: buildId,
        vpc_id: vpcId,
        private_subnet_ids: JSON.stringify(privateSubnetIds),
        public_subnet_ids: JSON.stringify(publicSubnetIds),
        aws_region: process.env.AWS_REGION || 'us-east-1'
      }
    });

    const output = getTerraformOutputJson(monolithDir);
    const albUrl = output.alb_dns_name?.value;

    console.log('\n✓ Monolith deployed to AWS ECS');
    if (albUrl) {
      console.log(`ALB URL: http://${albUrl}`);
      return [`http://${albUrl}/health`];
    }

    return [];

  } catch (error) {
    console.error('\n❌ Monolith deployment failed:', error.message);
    throw error;
  }
}

/**
 * Destroy monolith deployment
 */
async function destroyMonolith(experiment) {
  console.log(`Destroying monolith deployment for experiment: ${experiment}`);

  const projectRoot = path.join(__dirname, '..');
  const monolithDir = path.join(projectRoot, 'infrastructure', 'monolith', 'aws');

  if (fs.existsSync(monolithDir)) {
    console.log('Destroying ECS infrastructure...');
    runTerraform(monolithDir, 'destroy', { autoApprove: true });
  }

  // Also destroy VPC if needed
  const vpcDir = path.join(projectRoot, 'infrastructure', 'services', 'vpc');
  if (fs.existsSync(vpcDir)) {
    console.log('Destroying VPC...');
    runTerraform(vpcDir, 'destroy', { autoApprove: true });
  }

  console.log('✓ Monolith infrastructure destroyed');
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

module.exports = { deployMonolith, destroyMonolith };