const fs = require('fs');
const path = require('path');

// Helper function to recursively copy a directory
function copyDirRecursive(src, dest) {
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(dest, { recursive: true });
  }

  const entries = fs.readdirSync(src, { withFileTypes: true });

  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);

    if (entry.isDirectory()) {
      copyDirRecursive(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

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

  // 4. Create functions directory and copy all functions (including subdirectories like html_templates)
  const functionsDir = path.join(tmpDir, 'functions');
  if (!fs.existsSync(functionsDir)) {
    fs.mkdirSync(functionsDir, { recursive: true });
  }

  const sourceFunctionsDir = path.join(__dirname, '..', '..', 'functions');
  const functionNames = fs.readdirSync(sourceFunctionsDir).filter(file => {
    const fullPath = path.join(sourceFunctionsDir, file);
    return fs.statSync(fullPath).isDirectory();
  });

  // Get auth strategy files
  const authStrategyDir = path.join(__dirname, '..', '..', 'authentication', authStrategy);
  const authFiles = fs.readdirSync(authStrategyDir).filter(file => {
    return fs.statSync(path.join(authStrategyDir, file)).isFile();
  });

  // Functions that should use mock handlers in 'none' auth mode
  const authMockFunctions = ['login', 'register'];

  console.log(`  Copying ${functionNames.length} functions...`);
  functionNames.forEach(functionName => {
    const srcFunctionDir = path.join(sourceFunctionsDir, functionName);
    const destFunctionDir = path.join(functionsDir, functionName);

    // Recursively copy the entire function directory (includes html_templates, etc.)
    copyDirRecursive(srcFunctionDir, destFunctionDir);

    // For 'none' auth strategy, use mock handlers for login and register to skip Cognito calls
    if (authStrategy === 'none' && authMockFunctions.includes(functionName)) {
      const mockHandlerPath = path.join(authStrategyDir, `${functionName}.js`);
      if (fs.existsSync(mockHandlerPath)) {
        const destIndexPath = path.join(destFunctionDir, 'index.js');
        fs.copyFileSync(mockHandlerPath, destIndexPath);
        console.log(`    Using mock ${functionName} handler for 'none' auth strategy`);
      }
    }

    // Copy auth files into each function's directory (functions use require('./auth'))
    const destAuthDir = path.join(destFunctionDir, 'auth');
    if (!fs.existsSync(destAuthDir)) {
      fs.mkdirSync(destAuthDir, { recursive: true });
    }
    authFiles.forEach(file => {
      const srcPath = path.join(authStrategyDir, file);
      const destPath = path.join(destAuthDir, file);
      fs.copyFileSync(srcPath, destPath);
    });
  });

  // 5. Copy the auth strategy to root level too (for any top-level auth imports)
  const authDir = path.join(tmpDir, 'auth');
  if (!fs.existsSync(authDir)) {
    fs.mkdirSync(authDir, { recursive: true });
  }

  authFiles.forEach(file => {
    const srcPath = path.join(authStrategyDir, file);
    const destPath = path.join(authDir, file);
    fs.copyFileSync(srcPath, destPath);
  });

  // 6. Copy productcatalog data (used by product-related functions)
  const productcatalogSrc = path.join(__dirname, '..', '..', 'productcatalog');
  const productcatalogDest = path.join(tmpDir, 'productcatalog');
  if (fs.existsSync(productcatalogSrc)) {
    console.log('  Copying productcatalog...');
    copyDirRecursive(productcatalogSrc, productcatalogDest);
  }

  // 7. Copy currency data (used by currency functions)
  const currencySrc = path.join(__dirname, '..', '..', 'currency');
  const currencyDest = path.join(tmpDir, 'currency');
  if (fs.existsSync(currencySrc)) {
    console.log('  Copying currency data...');
    copyDirRecursive(currencySrc, currencyDest);
  }

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