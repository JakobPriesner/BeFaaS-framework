const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

/**
 * Bundles a directory using ncc and creates a zip file
 * @param {string} sourceDir - Directory containing the code to bundle
 * @param {string} outputZip - Path where the zip file should be created
 * @param {Object} options - Additional options
 * @param {string} options.entryPoint - Entry point file (default: 'index.js')
 * @param {boolean} options.minify - Whether to minify the output (default: false)
 */
function bundleAndZip(sourceDir, outputZip, options = {}) {
  const { entryPoint = 'index.js', minify = false } = options;

  console.log(`  Bundling ${sourceDir}...`);

  const buildDir = path.join(sourceDir, '_build');
  const entryFile = path.join(sourceDir, entryPoint);

  // Ensure the entry file exists
  if (!fs.existsSync(entryFile)) {
    throw new Error(`Entry file not found: ${entryFile}`);
  }

  // Create build directory
  if (fs.existsSync(buildDir)) {
    fs.rmSync(buildDir, { recursive: true });
  }
  fs.mkdirSync(buildDir, { recursive: true });

  // Bundle with ncc
  const nccCmd = `npx ncc build ${entryFile} -o ${buildDir}${minify ? ' --minify' : ''}`;
  try {
    execSync(nccCmd, { stdio: 'pipe', cwd: path.resolve('.') });
  } catch (error) {
    console.error(`Failed to bundle ${sourceDir}: ${error.message}`);
    throw error;
  }

  // Create minimal package.json in build directory
  const packageJson = {
    name: path.basename(sourceDir),
    version: '1.0.0',
    main: 'index.js'
  };
  fs.writeFileSync(
    path.join(buildDir, 'package.json'),
    JSON.stringify(packageJson, null, 2)
  );

  // Create zip file
  const outputDir = path.dirname(outputZip);
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  console.log(`  Creating zip: ${outputZip}`);
  try {
    execSync(`cd ${buildDir} && zip -r ${path.resolve(outputZip)} .`, { stdio: 'pipe' });
  } catch (error) {
    console.error(`Failed to create zip for ${sourceDir}: ${error.message}`);
    throw error;
  }

  // Clean up build directory
  fs.rmSync(buildDir, { recursive: true });

  console.log(`  ✓ Created ${outputZip}`);
}

/**
 * Installs npm dependencies in a directory
 * @param {string} dir - Directory where to run npm install
 * @param {boolean} production - Whether to install only production dependencies
 */
function installDependencies(dir, production = true) {
  if (!fs.existsSync(path.join(dir, 'package.json'))) {
    console.warn(`  No package.json found in ${dir}, skipping npm install`);
    return;
  }

  console.log(`  Installing dependencies in ${dir}...`);
  const cmd = production ? 'npm install --production' : 'npm install';

  try {
    execSync(cmd, { stdio: 'inherit', cwd: dir });
  } catch (error) {
    console.error(`Failed to install dependencies in ${dir}: ${error.message}`);
    throw error;
  }
}

/**
 * Creates a Docker image for a service
 * @param {string} serviceDir - Directory containing the service code and Dockerfile
 * @param {string} imageName - Name for the Docker image
 * @param {string} tag - Tag for the Docker image (default: 'latest')
 */
function buildDockerImage(serviceDir, imageName, tag = 'latest') {
  if (!fs.existsSync(path.join(serviceDir, 'Dockerfile'))) {
    throw new Error(`Dockerfile not found in ${serviceDir}`);
  }

  console.log(`  Building Docker image ${imageName}:${tag}...`);

  try {
    execSync(`docker build -t ${imageName}:${tag} ${serviceDir}`, { stdio: 'inherit' });
    console.log(`  ✓ Built image ${imageName}:${tag}`);
  } catch (error) {
    console.error(`Failed to build Docker image: ${error.message}`);
    throw error;
  }
}

/**
 * Pushes a Docker image to a registry
 * @param {string} imageName - Name of the Docker image
 * @param {string} tag - Tag of the Docker image (default: 'latest')
 */
function pushDockerImage(imageName, tag = 'latest') {
  console.log(`  Pushing Docker image ${imageName}:${tag}...`);

  try {
    execSync(`docker push ${imageName}:${tag}`, { stdio: 'inherit' });
    console.log(`  ✓ Pushed image ${imageName}:${tag}`);
  } catch (error) {
    console.error(`Failed to push Docker image: ${error.message}`);
    throw error;
  }
}

/**
 * Creates a simple zip (without bundling) for deployment
 * @param {string} sourceDir - Directory to zip
 * @param {string} outputZip - Path where the zip file should be created
 */
function createZip(sourceDir, outputZip) {
  const outputDir = path.dirname(outputZip);
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  console.log(`  Creating zip: ${outputZip}`);
  try {
    execSync(`cd ${sourceDir} && zip -r ${path.resolve(outputZip)} .`, { stdio: 'pipe' });
    console.log(`  ✓ Created ${outputZip}`);
  } catch (error) {
    console.error(`Failed to create zip: ${error.message}`);
    throw error;
  }
}

/**
 * Cleans a directory by removing it and recreating it
 * @param {string} dir - Directory to clean
 */
function cleanDirectory(dir) {
  if (fs.existsSync(dir)) {
    fs.rmSync(dir, { recursive: true });
  }
  fs.mkdirSync(dir, { recursive: true });
}

module.exports = {
  bundleAndZip,
  installDependencies,
  buildDockerImage,
  pushDockerImage,
  createZip,
  cleanDirectory
};