const fs = require('fs');
const path = require('path');

async function build(tmpDir, authStrategy) {
  console.log(`Building Monolith architecture with auth strategy: ${authStrategy}`);

  // Create the temporary directory, if not exists
  if (!fs.existsSync(tmpDir)) {
    fs.mkdirSync(tmpDir, { recursive: true });
  }

  // 1. Copy the monolith index.js
  const indexPath = path.join(__dirname, 'index.js');
  const destIndexPath = path.join(tmpDir, 'index.js');
  fs.copyFileSync(indexPath, destIndexPath);

  // 2. Copy the package.json
  const packagePath = path.join(__dirname, 'package.json');
  const destPackagePath = path.join(tmpDir, 'package.json');
  fs.copyFileSync(packagePath, destPackagePath);

  // 3. Copy Dockerfile if exists
  const dockerfilePath = path.join(__dirname, 'Dockerfile');
  if (fs.existsSync(dockerfilePath)) {
    const destDockerfilePath = path.join(tmpDir, 'Dockerfile');
    fs.copyFileSync(dockerfilePath, destDockerfilePath);
  }

  // 4. Create functions directory and copy all functions
  const functionsDir = path.join(tmpDir, 'functions');
  if (!fs.existsSync(functionsDir)) {
    fs.mkdirSync(functionsDir, { recursive: true });
  }

  const sourceFunctionsDir = path.join(__dirname, '..', '..', 'functions');
  const functionNames = fs.readdirSync(sourceFunctionsDir).filter(file => {
    const fullPath = path.join(sourceFunctionsDir, file);
    return fs.statSync(fullPath).isDirectory();
  });

  console.log(`  Copying ${functionNames.length} functions...`);
  functionNames.forEach(functionName => {
    const functionDir = path.join(functionsDir, functionName);
    if (!fs.existsSync(functionDir)) {
      fs.mkdirSync(functionDir, { recursive: true });
    }

    const srcPath = path.join(sourceFunctionsDir, functionName, 'index.js');
    const destPath = path.join(functionDir, 'index.js');
    fs.copyFileSync(srcPath, destPath);
  });

  // 5. Copy the auth strategy
  const authDir = path.join(tmpDir, 'auth');
  if (!fs.existsSync(authDir)) {
    fs.mkdirSync(authDir, { recursive: true });
  }

  const authStrategyDir = path.join(__dirname, '..', '..', 'authentication', authStrategy);
  const authFiles = fs.readdirSync(authStrategyDir);

  authFiles.forEach(file => {
    const srcPath = path.join(authStrategyDir, file);
    const destPath = path.join(authDir, file);
    if (fs.statSync(srcPath).isFile()) {
      fs.copyFileSync(srcPath, destPath);
    }
  });

  console.log(`Build complete for Monolith in ${tmpDir}`);
}

module.exports = build;

// Allow running as a standalone script
if (require.main === module) {
  const authStrategy = process.argv[2] || 'none';
  const outputDir = process.argv[3] || path.join(__dirname, '_build');

  console.log(`Running build with auth: ${authStrategy}, output: ${outputDir}`);
  build(outputDir, authStrategy)
    .then(() => process.exit(0))
    .catch(error => {
      console.error('Build failed:', error);
      process.exit(1);
    });
}