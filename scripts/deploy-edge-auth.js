/**
 * Edge-based Authentication Deployment Script
 *
 * Orchestrates the deployment of CloudFront + Lambda@Edge for edge-based authentication.
 * This script:
 * 1. Generates Ed25519 key pairs (if not existing)
 * 2. Builds Lambda@Edge function with embedded JWKS
 * 3. Deploys CloudFront distribution
 * 4. Returns CloudFront endpoint and public key
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const crypto = require('crypto');
const { runTerraform, getTerraformOutputJson, hasState } = require('./deploy-shared');

/**
 * Generate Ed25519 key pair for token signing
 * @returns {{ publicKey: string, privateKey: string }} Base64-encoded DER keys
 */
function generateEd25519KeyPair() {
  const { generateKeyPairSync } = crypto;

  const { publicKey, privateKey } = generateKeyPairSync('ed25519', {
    publicKeyEncoding: { type: 'spki', format: 'der' },
    privateKeyEncoding: { type: 'pkcs8', format: 'der' }
  });

  return {
    publicKey: publicKey.toString('base64'),
    privateKey: privateKey.toString('base64')
  };
}

/**
 * Build Lambda@Edge function with embedded secrets.
 *
 * Two JWKS delivery modes are supported:
 *   - 'runtime'   (default, production-faithful): the Lambda@Edge function
 *                 fetches the Cognito JWKS on first use from the public
 *                 /.well-known/jwks.json endpoint and caches it at module
 *                 scope. Mirrors the aws-jwt-verify behaviour used by the
 *                 backend Cognito strategy; required for a fair comparison.
 *   - 'buildtime' (legacy, preserved for reproducibility of the original
 *                 experiment series E44/E51/E100/E102/...): the deploy step
 *                 fetches the JWKS once and embeds it as a JSON literal into
 *                 the function source. No runtime fetch, no key rotation
 *                 without redeployment.
 *
 * See evaluation/bedrohung_der_validität.tex for the construct validity
 * discussion that motivates keeping both variants deployable.
 */
async function buildEdgeLambda(projectRoot, cognitoPoolId, cognitoRegion, privateKey, cognitoClientId, jwksMode = 'runtime') {
  if (jwksMode !== 'runtime' && jwksMode !== 'buildtime') {
    throw new Error(`Invalid jwksMode '${jwksMode}' (expected 'runtime' or 'buildtime')`);
  }
  console.log(`Building Lambda@Edge function (jwksMode=${jwksMode})...`);

  const edgeLambdaDir = path.join(
    projectRoot,
    'experiments',
    'webservice',
    'authentication',
    'edge',
    'edge-lambda'
  );

  const buildDir = path.join(edgeLambdaDir, 'dist');

  // Create build directory
  if (!fs.existsSync(buildDir)) {
    fs.mkdirSync(buildDir, { recursive: true });
  }

  // Select the source variant matching the requested jwksMode.
  const sourceFileName = jwksMode === 'buildtime'
    ? 'index.legacy-buildtime-jwks.js'
    : 'index.js';
  const sourcePath = path.join(edgeLambdaDir, sourceFileName);
  let sourceCode = fs.readFileSync(sourcePath, 'utf8');
  console.log(`  Source variant: ${sourceFileName}`);

  const jwksUrl = `https://cognito-idp.${cognitoRegion}.amazonaws.com/${cognitoPoolId}/.well-known/jwks.json`;

  if (jwksMode === 'runtime') {
    // Inline only the JWKS URL; the function fetches keys at runtime.
    sourceCode = sourceCode.replace(
      /const COGNITO_JWKS_URL = process\.env\.COGNITO_JWKS_URL;/,
      `const COGNITO_JWKS_URL = '${jwksUrl}';`
    );
  } else {
    // Legacy variant: fetch JWKS once at deploy time and embed as JSON literal.
    console.log('  Fetching Cognito JWKS for build-time embedding...');
    let jwks;
    try {
      const response = await fetch(jwksUrl);
      if (!response.ok) {
        throw new Error(`Failed to fetch JWKS: ${response.status}`);
      }
      jwks = await response.json();
      console.log(`  Fetched ${jwks.keys?.length || 0} keys from JWKS`);
    } catch (error) {
      console.error(`  Failed to fetch JWKS from ${jwksUrl}:`, error.message);
      throw error;
    }

    sourceCode = sourceCode.replace(
      /const COGNITO_JWKS = process\.env\.COGNITO_JWKS \? JSON\.parse\(process\.env\.COGNITO_JWKS\) : null;/,
      `const COGNITO_JWKS = ${JSON.stringify(jwks)};`
    );
  }

  sourceCode = sourceCode.replace(
    /const EDGE_PRIVATE_KEY = process\.env\.EDGE_PRIVATE_KEY;/,
    `const EDGE_PRIVATE_KEY = '${privateKey}';`
  );

  // Embed Cognito issuer and client ID for token validation
  const cognitoIssuer = `https://cognito-idp.${cognitoRegion}.amazonaws.com/${cognitoPoolId}`;
  sourceCode = sourceCode.replace(
    /const COGNITO_ISSUER = process\.env\.COGNITO_ISSUER;/,
    `const COGNITO_ISSUER = '${cognitoIssuer}';`
  );

  sourceCode = sourceCode.replace(
    /const COGNITO_CLIENT_ID = process\.env\.COGNITO_CLIENT_ID;/,
    `const COGNITO_CLIENT_ID = '${cognitoClientId}';`
  );

  // Write bundled source
  const bundledPath = path.join(buildDir, 'index.js');
  fs.writeFileSync(bundledPath, sourceCode);

  // Create zip file
  const zipPath = path.join(buildDir, 'edge-lambda.zip');
  execSync('zip -j edge-lambda.zip index.js', {
    cwd: buildDir,
    stdio: 'pipe'
  });

  console.log(`  Lambda@Edge package created: ${zipPath}`);

  // Verify package size (must be < 1MB for Lambda@Edge)
  const stats = fs.statSync(zipPath);
  const sizeMB = stats.size / (1024 * 1024);
  console.log(`  Package size: ${sizeMB.toFixed(2)} MB`);

  if (sizeMB > 1) {
    throw new Error(`Lambda@Edge package too large: ${sizeMB.toFixed(2)} MB (max 1 MB)`);
  }

  return zipPath;
}

/**
 * Deploy edge authentication infrastructure
 *
 * @param {string} projectName - Project name for resource naming
 * @param {string} originDomain - Domain of the origin (API Gateway or ALB)
 * @param {Object} options - Deployment options
 * @returns {Promise<Object>} Deployment results
 */
async function deployEdgeAuth(projectName, originDomain, options = {}) {
  const projectRoot = path.join(__dirname, '..');
  const awsRegion = process.env.AWS_REGION || 'us-east-1';

  const {
    originProtocol = 'https-only',
    originHttpPort = 80,
    originHttpsPort = 443,
    keyPair: providedKeyPair = null,
    selectiveEdgeRouting = false,
    protectedPaths = null,
    jwksMode = 'runtime'
  } = options;

  console.log('\n========================================');
  console.log('Deploying Edge Authentication');
  console.log(`  jwksMode: ${jwksMode}`);
  console.log('========================================\n');

  // Step 1: Get Cognito configuration
  console.log('Step 1: Getting Cognito configuration...');
  const cognitoDir = path.join(projectRoot, 'infrastructure', 'services', 'cognito');

  if (!fs.existsSync(path.join(cognitoDir, 'terraform.tfstate'))) {
    throw new Error('Cognito not deployed. Please ensure Cognito is deployed first.');
  }

  const cognitoOutput = getTerraformOutputJson(cognitoDir);
  const cognitoPoolId = cognitoOutput.cognito_user_pool_id?.value || cognitoOutput.COGNITO_USER_POOL_ID?.value;
  const cognitoClientId = cognitoOutput.cognito_client_id?.value || cognitoOutput.COGNITO_CLIENT_ID?.value;

  if (!cognitoPoolId) {
    throw new Error('Could not get Cognito User Pool ID from Terraform state');
  }

  if (!cognitoClientId) {
    throw new Error('Could not get Cognito Client ID from Terraform state');
  }

  console.log(`  Cognito Pool ID: ${cognitoPoolId}`);
  console.log(`  Cognito Client ID: ${cognitoClientId}`);

  // Step 2: Use provided keys or generate/retrieve Ed25519 keys
  console.log('\nStep 2: Setting up Ed25519 keys...');
  let keyPair = providedKeyPair;

  if (!keyPair) {
    // Check if keys already exist in SSM
    try {
      const existingPublicKey = execSync(
        `aws ssm get-parameter --name /${projectName}/edge-auth/public-key --query Parameter.Value --output text --region ${awsRegion}`,
        { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }
      ).trim();

      const existingPrivateKey = execSync(
        `aws ssm get-parameter --name /${projectName}/edge-auth/private-key --with-decryption --query Parameter.Value --output text --region us-east-1`,
        { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }
      ).trim();

      if (existingPublicKey && existingPrivateKey && existingPublicKey !== 'None' && existingPrivateKey !== 'None') {
        keyPair = { publicKey: existingPublicKey, privateKey: existingPrivateKey };
        console.log('  Using existing Ed25519 keys from SSM');
      } else {
        throw new Error('Keys not found');
      }
    } catch {
      keyPair = generateEd25519KeyPair();
      console.log('  Generated new Ed25519 key pair');
    }
  } else {
    console.log('  Using provided Ed25519 keys');
  }

  // Step 3: Build Lambda@Edge function
  console.log('\nStep 3: Building Lambda@Edge function...');
  const lambdaZipPath = await buildEdgeLambda(
    projectRoot,
    cognitoPoolId,
    awsRegion,
    keyPair.privateKey,
    cognitoClientId,
    jwksMode
  );

  // Step 4: Deploy CloudFront and Lambda@Edge
  console.log('\nStep 4: Deploying CloudFront distribution...');
  const edgeAuthDir = path.join(projectRoot, 'infrastructure', 'services', 'edge-auth');

  // Generate a CloudFront secret for origin identification
  const cloudfrontSecret = crypto.randomBytes(32).toString('hex');

  // Write sensitive vars to auto.tfvars.json
  const tfvarsPath = path.join(edgeAuthDir, 'terraform.auto.tfvars.json');
  const tfvars = {
    project_name: projectName,
    origin_domain: originDomain,
    origin_protocol_policy: originProtocol,
    origin_http_port: originHttpPort,
    origin_https_port: originHttpsPort,
    edge_lambda_zip_path: lambdaZipPath,
    ed25519_public_key: keyPair.publicKey,
    ed25519_private_key: keyPair.privateKey,
    cloudfront_secret: cloudfrontSecret,
    aws_region: awsRegion,
    selective_edge_routing: selectiveEdgeRouting
  };
  if (protectedPaths) {
    tfvars.protected_paths = protectedPaths;
  }
  fs.writeFileSync(tfvarsPath, JSON.stringify(tfvars, null, 2));

  if (selectiveEdgeRouting) {
    console.log('  Selective edge routing ENABLED: only protected paths use Lambda@Edge');
  }

  // Run Terraform
  let output;
  try {
    runTerraform(edgeAuthDir, 'init');
    runTerraform(edgeAuthDir, 'apply');

    // Get outputs
    output = getTerraformOutputJson(edgeAuthDir);
  } finally {
    // Clean up tfvars file (contains sensitive data) even if deploy fails
    if (fs.existsSync(tfvarsPath)) fs.unlinkSync(tfvarsPath);
  }

  const cloudfrontDomain = output.cloudfront_domain?.value;
  const cloudfrontUrl = output.cloudfront_url?.value || `https://${cloudfrontDomain}`;

  console.log('\n========================================');
  console.log('Edge Authentication Deployed');
  console.log('========================================');
  console.log(`CloudFront Domain: ${cloudfrontDomain}`);
  console.log(`CloudFront URL: ${cloudfrontUrl}`);
  console.log('========================================\n');

  return {
    cloudfrontDomain,
    cloudfrontUrl,
    publicKey: keyPair.publicKey,
    distributionId: output.cloudfront_distribution_id?.value
  };
}

/**
 * Destroy edge authentication infrastructure
 */
async function destroyEdgeAuth(projectName) {
  const projectRoot = path.join(__dirname, '..');
  const edgeAuthDir = path.join(projectRoot, 'infrastructure', 'services', 'edge-auth');

  console.log('\nDestroying Edge Authentication infrastructure...');

  if (!fs.existsSync(path.join(edgeAuthDir, 'terraform.tfstate'))) {
    console.log('No edge-auth state found, skipping...');
    return;
  }

  try {
    // Need to provide vars for destroy
    const tfvarsPath = path.join(edgeAuthDir, 'terraform.auto.tfvars.json');

    // Read existing state to get values
    const currentVars = fs.existsSync(tfvarsPath)
      ? JSON.parse(fs.readFileSync(tfvarsPath, 'utf8'))
      : {};

    // Provide minimal vars for destroy
    fs.writeFileSync(tfvarsPath, JSON.stringify({
      project_name: projectName || currentVars.project_name || 'befaas',
      origin_domain: currentVars.origin_domain || 'placeholder.example.com',
      edge_lambda_zip_path: currentVars.edge_lambda_zip_path || '/tmp/placeholder.zip',
      ed25519_public_key: currentVars.ed25519_public_key || 'placeholder',
      ed25519_private_key: currentVars.ed25519_private_key || 'placeholder',
      cloudfront_secret: currentVars.cloudfront_secret || 'placeholder'
    }, null, 2));

    runTerraform(edgeAuthDir, 'destroy');

    // Clean up tfvars
    if (fs.existsSync(tfvarsPath)) {
      fs.unlinkSync(tfvarsPath);
    }

    console.log('✓ Edge Authentication infrastructure destroyed');

    // Note: Lambda@Edge replicas may persist for a while after destruction
    console.log('\nNote: Lambda@Edge replicas may take up to 30 minutes to be fully deleted.');
    console.log('This may block re-deployment during this period.');

  } catch (error) {
    console.error('Warning: Failed to destroy edge-auth:', error.message);
  }
}

/**
 * Check if edge-auth Terraform state exists with resources
 * @returns {boolean}
 */
function hasEdgeAuthState() {
  const projectRoot = path.join(__dirname, '..');
  const edgeAuthDir = path.join(projectRoot, 'infrastructure', 'services', 'edge-auth');
  return hasState(edgeAuthDir);
}

/**
 * Read edge-auth Terraform outputs
 * @returns {Object|null} Object with project_name, EDGE_PUBLIC_KEY, cloudfront_distribution_id, cloudfront_url — or null if incomplete
 */
function getEdgeAuthState() {
  const projectRoot = path.join(__dirname, '..');
  const edgeAuthDir = path.join(projectRoot, 'infrastructure', 'services', 'edge-auth');

  try {
    const output = getTerraformOutputJson(edgeAuthDir);

    const projectName = output.project_name?.value;
    const publicKey = output.EDGE_PUBLIC_KEY?.value;
    const distributionId = output.cloudfront_distribution_id?.value;
    const cloudfrontUrl = output.cloudfront_url?.value;

    if (!projectName || !publicKey || !distributionId || !cloudfrontUrl) {
      return null;
    }

    return { projectName, publicKey, distributionId, cloudfrontUrl };
  } catch {
    return null;
  }
}

/**
 * In-place update of existing edge-auth infrastructure (new origin, new Lambda code)
 *
 * @param {string} originDomain - New origin domain
 * @param {Object} options - Update options
 * @returns {Promise<Object>} Updated deployment results
 */
async function updateEdgeAuth(originDomain, options = {}) {
  const projectRoot = path.join(__dirname, '..');
  const edgeAuthDir = path.join(projectRoot, 'infrastructure', 'services', 'edge-auth');

  const {
    originProtocol = 'https-only',
    originHttpPort = 80,
    originHttpsPort = 443,
    selectiveEdgeRouting = false,
    protectedPaths = null,
    jwksMode = 'runtime'
  } = options;

  console.log('\n========================================');
  console.log('Updating Edge Authentication (in-place)');
  console.log(`  jwksMode: ${jwksMode}`);
  console.log('========================================\n');

  // Step 1: Read existing project_name + public key from edge-auth Terraform outputs
  console.log('Step 1: Reading existing edge-auth state...');
  const existingState = getEdgeAuthState();
  if (!existingState) {
    throw new Error('Cannot read existing edge-auth state for in-place update');
  }

  const { projectName, publicKey } = existingState;
  console.log(`  Project name: ${projectName}`);
  console.log(`  Distribution ID: ${existingState.distributionId}`);

  // Step 2: Read private key from SSM
  console.log('\nStep 2: Reading private key from SSM...');
  let privateKey;
  try {
    privateKey = execSync(
      `aws ssm get-parameter --name /${projectName}/edge-auth/private-key --with-decryption --query Parameter.Value --output text --region us-east-1`,
      { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }
    ).trim();
  } catch (error) {
    throw new Error(`Could not read private key from SSM: ${error.message}`);
  }
  console.log('  Private key retrieved from SSM');

  // Step 3: Get Cognito config from cognito Terraform state
  console.log('\nStep 3: Getting Cognito configuration...');
  const cognitoDir = path.join(projectRoot, 'infrastructure', 'services', 'cognito');
  const cognitoOutput = getTerraformOutputJson(cognitoDir);
  const cognitoPoolId = cognitoOutput.cognito_user_pool_id?.value || cognitoOutput.COGNITO_USER_POOL_ID?.value;
  const cognitoClientId = cognitoOutput.cognito_client_id?.value || cognitoOutput.COGNITO_CLIENT_ID?.value;
  const awsRegion = process.env.AWS_REGION || 'us-east-1';

  if (!cognitoPoolId || !cognitoClientId) {
    throw new Error('Could not get Cognito configuration from Terraform state');
  }
  console.log(`  Cognito Pool ID: ${cognitoPoolId}`);
  console.log(`  Cognito Client ID: ${cognitoClientId}`);

  // Step 4: Build new Lambda@Edge zip with existing keys + fresh Cognito JWKS
  console.log('\nStep 4: Building Lambda@Edge function...');
  const lambdaZipPath = await buildEdgeLambda(
    projectRoot,
    cognitoPoolId,
    awsRegion,
    privateKey,
    cognitoClientId,
    jwksMode
  );

  // Step 5: Write terraform.auto.tfvars.json with same project_name + new origin
  console.log('\nStep 5: Applying Terraform changes...');
  const cloudfrontSecret = crypto.randomBytes(32).toString('hex');
  const tfvarsPath = path.join(edgeAuthDir, 'terraform.auto.tfvars.json');
  const updateTfvars = {
    project_name: projectName,
    origin_domain: originDomain,
    origin_protocol_policy: originProtocol,
    origin_http_port: originHttpPort,
    origin_https_port: originHttpsPort,
    edge_lambda_zip_path: lambdaZipPath,
    ed25519_public_key: publicKey,
    ed25519_private_key: privateKey,
    cloudfront_secret: cloudfrontSecret,
    aws_region: awsRegion,
    selective_edge_routing: selectiveEdgeRouting
  };
  if (protectedPaths) {
    updateTfvars.protected_paths = protectedPaths;
  }
  fs.writeFileSync(tfvarsPath, JSON.stringify(updateTfvars, null, 2));

  if (selectiveEdgeRouting) {
    console.log('  Selective edge routing ENABLED: only protected paths use Lambda@Edge');
  }

  // Step 6: Run terraform init + apply (in-place update)
  let output;
  try {
    runTerraform(edgeAuthDir, 'init');
    runTerraform(edgeAuthDir, 'apply');

    // Get outputs
    output = getTerraformOutputJson(edgeAuthDir);
  } finally {
    // Clean up tfvars file (contains sensitive data) even if deploy fails
    if (fs.existsSync(tfvarsPath)) fs.unlinkSync(tfvarsPath);
  }

  // Step 7: Invalidate CloudFront cache
  const distributionId = output.cloudfront_distribution_id?.value;
  if (distributionId) {
    console.log('\nStep 6: Invalidating CloudFront cache...');
    try {
      execSync(
        `aws cloudfront create-invalidation --distribution-id ${distributionId} --paths "/*" --region us-east-1`,
        { stdio: ['pipe', 'pipe', 'pipe'] }
      );
      console.log('  CloudFront cache invalidation created');
    } catch (invalidationError) {
      console.warn('  Warning: CloudFront cache invalidation failed:', invalidationError.message);
      console.warn('  (TTLs are 0, caching is effectively disabled)');
    }
  }

  const cloudfrontDomain = output.cloudfront_domain?.value;
  const cloudfrontUrl = output.cloudfront_url?.value || `https://${cloudfrontDomain}`;

  console.log('\n========================================');
  console.log('Edge Authentication Updated (in-place)');
  console.log('========================================');
  console.log(`CloudFront Domain: ${cloudfrontDomain}`);
  console.log(`CloudFront URL: ${cloudfrontUrl}`);
  console.log(`Distribution ID: ${distributionId}`);
  console.log('========================================\n');

  return {
    cloudfrontDomain,
    cloudfrontUrl,
    publicKey,
    distributionId
  };
}

module.exports = {
  deployEdgeAuth,
  destroyEdgeAuth,
  generateEd25519KeyPair,
  buildEdgeLambda,
  hasEdgeAuthState,
  getEdgeAuthState,
  updateEdgeAuth
};