const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

/**
 * Run a Terraform command in a working directory
 * @param {string} workingDir - Directory to run terraform in
 * @param {string} command - Terraform command (init, apply, destroy, etc.)
 * @param {Object} options - Additional options
 * @param {Object} options.vars - Terraform variables
 * @param {string[]} options.targets - Multiple -target flags
 * @param {string} options.target - Single -target flag
 */
function runTerraform(workingDir, command, options = {}) {
  const { vars = {}, targets = [], target = null } = options;

  let cmd = `terraform ${command}`;

  // Add target if specified (single target)
  if (target) {
    cmd += ` -target=${target}`;
  }

  // Add targets if specified (multiple targets)
  // Use single quotes around targets to preserve inner double quotes for map keys
  if (targets.length > 0) {
    targets.forEach(t => {
      cmd += ` -target='${t}'`;
    });
  }

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

/**
 * Get all Terraform outputs as JSON
 * @param {string} workingDir - Directory to run terraform in
 * @returns {Object} Parsed JSON output
 */
function getTerraformOutputJson(workingDir) {
  try {
    const cmd = 'terraform output -json';
    const result = execSync(cmd, {
      cwd: workingDir,
      encoding: 'utf8',
      stdio: ['pipe', 'pipe', 'pipe']
    });
    return JSON.parse(result);
  } catch (error) {
    console.warn(`Warning: Could not get Terraform output from ${workingDir}`);
    return {};
  }
}

/**
 * Get a single Terraform output value
 * @param {string} workingDir - Directory to run terraform in
 * @param {string} outputName - Name of the output variable
 * @returns {string} The output value
 */
function getTerraformOutput(workingDir, outputName) {
  const cmd = `terraform output -raw ${outputName}`;
  const result = execSync(cmd, {
    cwd: workingDir,
    encoding: 'utf8'
  });
  return result.trim();
}

/**
 * Check if a Terraform directory has state with resources
 * @param {string} workingDir - Directory to check
 * @returns {boolean}
 */
function hasState(workingDir) {
  const stateFile = path.join(workingDir, 'terraform.tfstate');
  if (!fs.existsSync(stateFile)) {
    return false;
  }
  try {
    const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
    return state.resources && state.resources.length > 0;
  } catch {
    return false;
  }
}

/**
 * Get the current AWS account ID
 * @returns {string} AWS account ID
 */
function getAwsAccountId() {
  try {
    const result = execSync('aws sts get-caller-identity --query Account --output text', {
      encoding: 'utf8',
      stdio: ['pipe', 'pipe', 'pipe']
    });
    return result.trim();
  } catch (error) {
    throw new Error('Could not get AWS account ID. Ensure AWS CLI is configured.');
  }
}

/**
 * Get VPC ID from terraform state
 * @param {string} vpcDir - VPC terraform directory
 * @returns {string|null} VPC ID or null
 */
function getVpcIdFromState(vpcDir) {
  try {
    const stateFile = path.join(vpcDir, 'terraform.tfstate');
    if (!fs.existsSync(stateFile)) return null;

    const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
    if (!state.resources) return null;

    for (const resource of state.resources) {
      if (resource.type === 'aws_vpc' && resource.name === 'default') {
        return resource.instances?.[0]?.attributes?.id;
      }
    }
    return null;
  } catch (error) {
    return null;
  }
}

/**
 * Wait for EC2 instances in a VPC to be fully terminated
 * @param {string} vpcId - The VPC ID to check for instances
 * @param {string} awsRegion - AWS region
 * @param {number} maxWaitSeconds - Maximum time to wait (default: 300s)
 * @returns {Promise<boolean>} Whether all instances are terminated
 */
async function waitForInstancesTerminated(vpcId, awsRegion, maxWaitSeconds = 300) {
  console.log(`Waiting for EC2 instances in VPC ${vpcId} to terminate...`);
  const startTime = Date.now();
  const maxWaitMs = maxWaitSeconds * 1000;

  while (Date.now() - startTime < maxWaitMs) {
    try {
      // Check for any instances that are not terminated
      const result = execSync(
        `aws ec2 describe-instances --filters "Name=vpc-id,Values=${vpcId}" "Name=instance-state-name,Values=pending,running,stopping,shutting-down" --query "Reservations[*].Instances[*].InstanceId" --output text --region ${awsRegion}`,
        { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }
      ).trim();

      if (!result || result === '') {
        console.log('  ✓ All instances terminated');
        return true;
      }

      const instanceIds = result.split(/\s+/).filter(id => id);
      console.log(`  Waiting for ${instanceIds.length} instance(s) to terminate: ${instanceIds.join(', ')}`);
      await new Promise(resolve => setTimeout(resolve, 10000)); // Wait 10s between checks
    } catch (error) {
      // If the command fails, VPC might not exist, which is fine
      console.log('  Could not check instances, proceeding...');
      return true;
    }
  }

  console.log(`  ⚠ Timeout waiting for instances to terminate after ${maxWaitSeconds}s`);
  return false;
}

/**
 * Release any remaining ENIs in a VPC
 * @param {string} vpcId - The VPC ID
 * @param {string} awsRegion - AWS region
 */
async function cleanupVpcNetworkInterfaces(vpcId, awsRegion) {
  console.log(`Cleaning up network interfaces in VPC ${vpcId}...`);

  try {
    // Get all ENIs in the VPC
    const result = execSync(
      `aws ec2 describe-network-interfaces --filters "Name=vpc-id,Values=${vpcId}" --query "NetworkInterfaces[*].{Id:NetworkInterfaceId,Status:Status,AttachmentId:Attachment.AttachmentId}" --output json --region ${awsRegion}`,
      { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }
    );

    const enis = JSON.parse(result);
    if (!enis || enis.length === 0) {
      console.log('  No network interfaces found');
      return;
    }

    console.log(`  Found ${enis.length} network interface(s)`);

    for (const eni of enis) {
      try {
        // Detach if attached
        if (eni.AttachmentId && eni.Status === 'in-use') {
          console.log(`  Detaching ENI ${eni.Id}...`);
          execSync(
            `aws ec2 detach-network-interface --attachment-id ${eni.AttachmentId} --force --region ${awsRegion}`,
            { stdio: 'pipe' }
          );
          // Wait for detachment
          await new Promise(resolve => setTimeout(resolve, 5000));
        }

        // Delete the ENI
        console.log(`  Deleting ENI ${eni.Id}...`);
        execSync(
          `aws ec2 delete-network-interface --network-interface-id ${eni.Id} --region ${awsRegion}`,
          { stdio: 'pipe' }
        );
        console.log(`  ✓ Deleted ENI ${eni.Id}`);
      } catch (error) {
        console.log(`  ⚠ Could not delete ENI ${eni.Id}: ${error.message}`);
      }
    }
  } catch (error) {
    console.log(`  Could not cleanup ENIs: ${error.message}`);
  }
}

module.exports = {
  runTerraform,
  getTerraformOutputJson,
  getTerraformOutput,
  hasState,
  getAwsAccountId,
  getVpcIdFromState,
  waitForInstancesTerminated,
  cleanupVpcNetworkInterfaces
};
