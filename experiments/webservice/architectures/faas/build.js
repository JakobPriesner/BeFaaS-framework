
const fs = require('fs');
const path = require('path');

function copyDirectoryRecursive(src, dest) {
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(dest, { recursive: true });
  }

  const entries = fs.readdirSync(src, { withFileTypes: true });

  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);

    if (entry.isDirectory()) {
      copyDirectoryRecursive(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

async function buildSingleFunction(useCase, tmpDir, authStrategy) {
  console.log(`Building FaaS architecture for use case: ${useCase}`);

  // 1. Create the temporary directory, if not exists
  if (!fs.existsSync(tmpDir)) {
    fs.mkdirSync(tmpDir, { recursive: true });
  }

  const useCaseDir = path.join(__dirname, '..', '..', 'functions', useCase);

  // Special handling for frontend function (uses router pattern)
  if (useCase === 'frontend') {
    console.log(`Frontend function detected - copying entire directory`);

    // Copy the entire frontend directory contents
    copyDirectoryRecursive(useCaseDir, tmpDir);

    // Copy package.json for dependencies
    const packagePath = path.join(__dirname, 'package.json');
    const destPackagePath = path.join(tmpDir, 'package.json');
    fs.copyFileSync(packagePath, destPackagePath);

    console.log(`Build complete for ${useCase} in ${tmpDir}`);
    return;
  }

  // Standard build process for non-frontend functions
  // 2. Copy ./index.js to tmpDir
  const indexPath = path.join(__dirname, 'index.js');
  const destIndexPath = path.join(tmpDir, 'index.js');
  fs.copyFileSync(indexPath, destIndexPath);

  // 3. Copy ./package.json to tmpDir
  const packagePath = path.join(__dirname, 'package.json');
  const destPackagePath = path.join(tmpDir, 'package.json');
  fs.copyFileSync(packagePath, destPackagePath);

  // 4. Copy the usecase from the experiments/webservice/functions/<usecase>/index.js to handler.js
  const useCasePath = path.join(useCaseDir, 'index.js');
  const handlerPath = path.join(tmpDir, 'handler.js');
  fs.copyFileSync(useCasePath, handlerPath);

  // 5. Copy the auth strategy from experiments/webservice/authentication/<authStrategy> to tmpDir/auth
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

  console.log(`Build complete for ${useCase} in ${tmpDir}`);
}

async function build(tmpDir, authStrategy) {
  console.log(`Building FaaS architecture with auth strategy: ${authStrategy}`);

  // Get all function names from the functions directory
  const functionsDir = path.join(__dirname, '..', '..', 'functions');
  const useCases = fs.readdirSync(functionsDir).filter(file => {
    // Exclude _build directory and other non-function directories
    if (file.startsWith('_') || file.startsWith('.')) {
      return false;
    }
    const fullPath = path.join(functionsDir, file);
    return fs.statSync(fullPath).isDirectory();
  });

  console.log(`Found ${useCases.length} functions to build: ${useCases.join(', ')}`);

  // Build each function in its own directory
  for (const useCase of useCases) {
    const functionDir = path.join(tmpDir, useCase);
    await buildSingleFunction(useCase, functionDir, authStrategy);
  }

  console.log(`Build complete for all functions in ${tmpDir}`);
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