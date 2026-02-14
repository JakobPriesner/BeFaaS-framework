const fs = require('fs');
const path = require('path');
const { logSection } = require('./utils');

async function runBuild(experiment, architecture, auth, bundleMode = 'minimal', algorithm = null) {
  logSection(`Building ${experiment}/${architecture} architecture with ${auth} auth${algorithm ? ` (algorithm: ${algorithm})` : ''}`);

  const projectRoot = path.join(__dirname, '..', '..');
  const buildScript = path.join(projectRoot, 'experiments', experiment, 'architectures', architecture, 'build.js');

  if (!fs.existsSync(buildScript)) {
    throw new Error(`Build script not found: ${buildScript}`);
  }

  // Import and run the build script
  const build = require(buildScript);
  const tmpDir = path.join(projectRoot, 'experiments', experiment, 'architectures', architecture, '_build');

  // Clean the build directory
  if (fs.existsSync(tmpDir)) {
    fs.rmSync(tmpDir, { recursive: true });
  }

  // Run architecture-specific build
  // Pass bundleMode for FaaS architecture (ignored by other architectures)
  // Pass algorithm for service-integrated-manual auth (selects algorithm variant)
  await build(tmpDir, auth, bundleMode, algorithm);

  console.log(`✓ Build completed successfully`);
  return tmpDir;
}

module.exports = {
  runBuild
};