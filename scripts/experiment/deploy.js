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

module.exports = {
  runDeploy,
  runDestroy,
  resetCognitoUserPool
};