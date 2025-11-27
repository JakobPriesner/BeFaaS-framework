
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

    // Copy experiment.json
    const experimentJsonPath = path.join(__dirname, '..', '..', 'experiment.json');
    const destExperimentJsonPath = path.join(tmpDir, 'experiment.json');
    if (fs.existsSync(experimentJsonPath)) {
      fs.copyFileSync(experimentJsonPath, destExperimentJsonPath);
    } else {
      console.warn(`  ⚠️  Warning: experiment.json not found at ${experimentJsonPath}`);
    }

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
  // Also rewrite require paths for shared modules
  const useCasePath = path.join(useCaseDir, 'index.js');
  const handlerPath = path.join(tmpDir, 'handler.js');

  let handlerCode = fs.readFileSync(useCasePath, 'utf8');

  // Rewrite require paths from ../../<module> to ./<module>
  // This is needed because in the Lambda package structure, shared modules are at the same level as handler.js
  handlerCode = handlerCode.replace(/require\(['"]\.\.\/\.\.\/([^'"]+)['"]\)/g, "require('./$1')");

  fs.writeFileSync(handlerPath, handlerCode, 'utf8');

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

  // 6. Copy shared modules that this function depends on
  const sharedModuleDeps = {
    'currency': ['currency/exchangerates.js'],
    'supportedcurrencies': ['currency/exchangerates.js'],
    'getproduct': ['productcatalog/products.js'],
    'listproducts': ['productcatalog/products.js'],
    'searchproducts': ['productcatalog/products.js']
  };

  if (sharedModuleDeps[useCase]) {
    console.log(`  Copying shared modules for ${useCase}...`);

    for (const modulePath of sharedModuleDeps[useCase]) {
      const parts = modulePath.split('/');
      const moduleDir = parts[0];
      const moduleFile = parts[1];

      // Create the module directory in tmpDir (e.g., tmpDir/currency/)
      const destModuleDir = path.join(tmpDir, moduleDir);
      if (!fs.existsSync(destModuleDir)) {
        fs.mkdirSync(destModuleDir, { recursive: true });
      }

      // Copy the shared module file
      const srcModulePath = path.join(__dirname, '..', '..', modulePath);
      const destModulePath = path.join(destModuleDir, moduleFile);

      if (fs.existsSync(srcModulePath)) {
        fs.copyFileSync(srcModulePath, destModulePath);
        console.log(`    ✓ Copied ${modulePath}`);
      } else {
        console.warn(`    ⚠️  Warning: Shared module not found: ${srcModulePath}`);
      }
    }
  }

  // 7. Copy experiment.json to tmpDir
  const experimentJsonPath = path.join(__dirname, '..', '..', 'experiment.json');
  const destExperimentJsonPath = path.join(tmpDir, 'experiment.json');
  if (fs.existsSync(experimentJsonPath)) {
    fs.copyFileSync(experimentJsonPath, destExperimentJsonPath);
  } else {
    console.warn(`  ⚠️  Warning: experiment.json not found at ${experimentJsonPath}`);
  }

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