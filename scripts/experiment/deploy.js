const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { logSection } = require('./utils');

async function runDeploy(experiment, architecture, buildDir) {
  logSection(`Deploying ${experiment}/${architecture} architecture`);

  try {
    let endpoints = [];

    switch (architecture) {
      case 'faas': {
        const { deployFaaS } = require('../deploy-faas');
        endpoints = await deployFaaS(experiment, buildDir);
        break;
      }

      case 'microservices': {
        const { deployMicroservices } = require('../deploy-microservices');
        endpoints = await deployMicroservices(experiment, buildDir);
        break;
      }

      case 'monolith': {
        const { deployMonolith } = require('../deploy-monolith');
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

async function runDestroy(experiment, architecture) {
  logSection(`Destroying ${experiment}/${architecture} infrastructure`);

  try {
    switch (architecture) {
      case 'faas': {
        const { destroyFaaS } = require('../deploy-faas');
        await destroyFaaS(experiment);
        break;
      }

      case 'microservices': {
        const { destroyMicroservices } = require('../deploy-microservices');
        await destroyMicroservices(experiment);
        break;
      }

      case 'monolith': {
        const { destroyMonolith } = require('../deploy-monolith');
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

/**
 * Reset Cognito User Pool (disabled by default)
 *
 * This function was previously used to recreate the Cognito pool before each benchmark,
 * but this caused issues with pre-registered users being deleted.
 *
 * If you need to reset the Cognito pool, you can:
 * 1. Use the AWS CLI to delete users: aws cognito-idp admin-delete-user
 * 2. Destroy and redeploy the infrastructure
 * 3. Manually taint the Cognito resources in Terraform
 *
 * @param {boolean} force - If true, actually reset the pool (default: false)
 */
async function resetCognitoUserPool(force = false) {
  if (!force) {
    console.log('Skipping Cognito User Pool reset (users are pre-registered)');
    return;
  }

  logSection('Resetting Cognito User Pool');

  const projectRoot = path.join(__dirname, '..', '..');
  const awsDir = path.join(projectRoot, 'infrastructure', 'aws');

  // Check if Cognito resources exist in state
  try {
    const stateList = execSync('terraform state list', {
      cwd: awsDir,
      encoding: 'utf8'
    });

    const cognitoResources = [
      'aws_cognito_user_pool.main',
      'aws_cognito_user_pool_client.main',
      'aws_cognito_user_pool_domain.main'
    ];

    const existingResources = cognitoResources.filter(r => stateList.includes(r));

    if (existingResources.length === 0) {
      console.log('No Cognito resources found in state, skipping reset');
      return;
    }

    // Taint Cognito resources to force recreation
    console.log('Tainting Cognito resources for recreation...');
    for (const resource of existingResources) {
      try {
        execSync(`terraform taint ${resource}`, {
          cwd: awsDir,
          stdio: 'pipe'
        });
        console.log(`  ✓ Tainted: ${resource}`);
      } catch (error) {
        console.log(`  ⚠ Could not taint ${resource}: ${error.message}`);
      }
    }

    // Apply to recreate the tainted resources
    console.log('\nRecreating Cognito resources...');
    execSync('terraform apply -auto-approve', {
      cwd: awsDir,
      stdio: 'inherit'
    });

    console.log('✓ Cognito User Pool reset successfully');

  } catch (error) {
    console.error('⚠ Failed to reset Cognito User Pool:', error.message);
    console.log('Continuing with existing Cognito configuration...');
  }
}

/**
 * Force destroy Redis containers by connecting to the EC2 instances and stopping Docker containers
 * This helps prevent hanging infrastructure when normal Terraform destroy fails
 */
async function forceDestroyRedis(experiment) {
  logSection('Force Destroying Redis Containers');

  const projectRoot = path.join(__dirname, '..', '..');

  // Check if experiment.json exists
  const experimentJsonPath = path.join(projectRoot, 'experiments', experiment, 'experiment.json');
  if (!fs.existsSync(experimentJsonPath)) {
    console.log('No experiment.json found, skipping Redis force destroy...');
    return;
  }

  const experimentConfig = JSON.parse(fs.readFileSync(experimentJsonPath, 'utf8'));

  // Only proceed if Redis service is configured
  if (!experimentConfig.services || !experimentConfig.services.redisAws) {
    console.log('No Redis AWS service configured, skipping...');
    return;
  }

  const redisDir = path.join(projectRoot, 'infrastructure', 'services', 'redisAws');

  // Check if Redis infrastructure state exists
  const redisStateFile = path.join(redisDir, 'terraform.tfstate');
  if (!fs.existsSync(redisStateFile)) {
    console.log('No Redis Terraform state found, skipping...');
    return;
  }

  try {
    // Get Redis instance information from Terraform state
    console.log('Getting Redis instance information...');
    const stateData = execSync('terraform show -json', {
      cwd: redisDir,
      encoding: 'utf8'
    });

    const state = JSON.parse(stateData);
    const redisInstances = [];

    // Find Redis instances in the state
    if (state.values && state.values.root_module && state.values.root_module.resources) {
      for (const resource of state.values.root_module.resources) {
        if (resource.type === 'aws_instance' && resource.name === 'redis' && resource.values) {
          redisInstances.push({
            publicIp: resource.values.public_ip,
            privateKey: resource.values.private_key || null
          });
        }
      }
    }

    if (redisInstances.length === 0) {
      console.log('No Redis instances found in Terraform state');
      return;
    }

    // Get SSH private key from VPC state
    const vpcDir = path.join(projectRoot, 'infrastructure', 'services', 'vpc');
    let privateKey = null;

    if (fs.existsSync(vpcDir)) {
      try {
        const vpcOutput = execSync('terraform output -json ssh_private_key', {
          cwd: vpcDir,
          encoding: 'utf8'
        });
        privateKey = JSON.parse(vpcOutput);
      } catch (error) {
        console.warn('Could not get SSH private key from VPC state:', error.message);
      }
    }

    // Force destroy containers on each Redis instance
    for (const instance of redisInstances) {
      console.log(`Attempting to force destroy containers on Redis instance ${instance.publicIp}...`);

      if (!instance.publicIp) {
        console.warn('No public IP found for Redis instance, skipping...');
        continue;
      }

      try {
        // Create temporary SSH key file if we have the private key
        const tempDir = fs.mkdtempSync(path.join(__dirname, 'temp-ssh-'));
        const keyFile = path.join(tempDir, 'key.pem');

        if (privateKey) {
          fs.writeFileSync(keyFile, privateKey, { mode: 0o600 });
        } else {
          console.warn('No SSH private key available, cannot connect to Redis instance');
          continue;
        }

        // Execute Docker stop and remove commands via SSH
        const sshCommands = [
          'sudo docker stop befaas-redis || true',
          'sudo docker rm befaas-redis || true',
          'sudo docker system prune -f || true'
        ];

        for (const command of sshCommands) {
          try {
            console.log(`  Running: ${command}`);
            execSync(`ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -i "${keyFile}" ubuntu@${instance.publicIp} "${command}"`, {
              timeout: 30000,
              stdio: 'pipe'
            });
            console.log(`  ✓ ${command} completed`);
          } catch (error) {
            console.log(`  ⚠ ${command} failed: ${error.message}`);
          }
        }

        // Cleanup temp files
        fs.rmSync(tempDir, { recursive: true, force: true });

        console.log(`✓ Force destroy completed for ${instance.publicIp}`);

      } catch (error) {
        console.warn(`Failed to force destroy containers on ${instance.publicIp}:`, error.message);
      }
    }

    // Also try to terminate instances directly via AWS CLI if available
    console.log('Attempting to terminate Redis instances via AWS CLI...');
    try {
      const instanceIds = [];

      // Get instance IDs from Terraform output
      try {
        const instanceId = execSync('terraform output -raw redis_instance_id', {
          cwd: redisDir,
          encoding: 'utf8'
        }).trim();

        if (instanceId && instanceId !== 'null') {
          instanceIds.push(instanceId);
        }
      } catch (error) {
        // Instance ID output might not exist, try to get it from state
        for (const resource of state.values.root_module.resources) {
          if (resource.type === 'aws_instance' && resource.name === 'redis' && resource.values.id) {
            instanceIds.push(resource.values.id);
          }
        }
      }

      if (instanceIds.length > 0) {
        console.log(`Found instance IDs: ${instanceIds.join(', ')}`);

        for (const instanceId of instanceIds) {
          try {
            execSync(`aws ec2 terminate-instances --instance-ids ${instanceId}`, {
              timeout: 10000,
              stdio: 'pipe'
            });
            console.log(`  ✓ Terminated instance ${instanceId}`);
          } catch (error) {
            console.log(`  ⚠ Failed to terminate instance ${instanceId}: ${error.message}`);
          }
        }
      }

    } catch (error) {
      console.warn('Could not terminate instances via AWS CLI:', error.message);
    }

    console.log('✓ Redis force destroy completed');

  } catch (error) {
    console.warn('Redis force destroy failed:', error.message);
  }
}

module.exports = {
  runDeploy,
  runDestroy,
  resetCognitoUserPool,
  forceDestroyRedis
};