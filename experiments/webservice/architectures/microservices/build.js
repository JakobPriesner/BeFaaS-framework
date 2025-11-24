const fs = require('fs');
const path = require('path');

// Define microservices and their functions
const services = {
  'cart-service': {
    functions: ['getcart', 'addcartitem', 'emptycart', 'cartkvstorage'],
    dependencies: {
      '@befaas/lib': '*',
      express: '^4.18.2',
      lodash: '^4.17.21',
      'aws-sdk': '^2.1400.0',
      axios: '^1.4.0'
    },
    port: 3002
  },
  'content-service': {
    functions: ['getads', 'supportedcurrencies', 'currency'],
    dependencies: {
      '@befaas/lib': '*',
      express: '^4.18.2',
      'aws-sdk': '^2.1400.0',
      axios: '^1.4.0'
    },
    port: 3004
  },
  'frontend-service': {
    functions: ['frontend'],
    dependencies: {
      '@befaas/lib': '*',
      express: '^4.18.2',
      'aws-sdk': '^2.1400.0',
      axios: '^1.4.0'
    },
    port: 3000
  },
  'order-service': {
    functions: ['checkout', 'payment', 'shipmentquote', 'email'],
    dependencies: {
      '@befaas/lib': '*',
      express: '^4.18.2',
      'aws-sdk': '^2.1400.0',
      axios: '^1.4.0'
    },
    port: 3003
  },
  'product-service': {
    functions: ['getproduct', 'listproducts', 'searchproducts', 'listrecommendations'],
    dependencies: {
      '@befaas/lib': '*',
      express: '^4.18.2',
      'aws-sdk': '^2.1400.0',
      axios: '^1.4.0'
    },
    port: 3001
  }
};

function copyFunctionToService(functionName, serviceDir) {
  const functionsDir = path.join(serviceDir, 'functions');
  const functionDir = path.join(functionsDir, functionName);

  if (!fs.existsSync(functionDir)) {
    fs.mkdirSync(functionDir, { recursive: true });
  }

  const srcPath = path.join(__dirname, '..', '..', 'functions', functionName, 'index.js');
  const destPath = path.join(functionDir, 'index.js');
  fs.copyFileSync(srcPath, destPath);
}

function copyAuthStrategy(serviceDir, authStrategy) {
  const authDir = path.join(serviceDir, 'auth');
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
}

function copySharedModules(serviceDir) {
  const sharedDir = path.join(serviceDir, 'shared');
  if (!fs.existsSync(sharedDir)) {
    fs.mkdirSync(sharedDir, { recursive: true });
  }

  const sharedSrcDir = path.join(__dirname, 'shared');
  const sharedFiles = fs.readdirSync(sharedSrcDir);

  sharedFiles.forEach(file => {
    const srcPath = path.join(sharedSrcDir, file);
    const destPath = path.join(sharedDir, file);
    if (fs.statSync(srcPath).isFile()) {
      fs.copyFileSync(srcPath, destPath);
    }
  });
}

function buildService(serviceName, serviceConfig, tmpDir, authStrategy) {
  console.log(`  Building ${serviceName}...`);

  const serviceDir = path.join(tmpDir, serviceName);
  const functionsDir = path.join(serviceDir, 'functions');

  // Create service directory structure
  if (!fs.existsSync(functionsDir)) {
    fs.mkdirSync(functionsDir, { recursive: true });
  }

  // Copy service index.js
  const serviceIndexPath = path.join(__dirname, serviceName, 'index.js');
  const destServiceIndexPath = path.join(serviceDir, 'index.js');
  fs.copyFileSync(serviceIndexPath, destServiceIndexPath);

  // Copy all functions for this service
  serviceConfig.functions.forEach(functionName => {
    copyFunctionToService(functionName, serviceDir);
  });

  // Copy shared modules (service discovery, etc.)
  copySharedModules(serviceDir);

  // Copy auth strategy
  copyAuthStrategy(serviceDir, authStrategy);

  // Create package.json
  const packageJson = {
    name: serviceName,
    version: '1.0.0',
    description: `${serviceName} microservice`,
    main: 'index.js',
    dependencies: serviceConfig.dependencies,
    scripts: {
      start: 'node index.js'
    }
  };

  const packageJsonPath = path.join(serviceDir, 'package.json');
  fs.writeFileSync(packageJsonPath, JSON.stringify(packageJson, null, 2));
}

async function build(tmpDir, authStrategy) {
  console.log(`Building Microservices architecture for use case`);

  // Create the temporary directory, if not exists
  if (!fs.existsSync(tmpDir)) {
    fs.mkdirSync(tmpDir, { recursive: true });
  }

  // Build all services
  Object.entries(services).forEach(([serviceName, serviceConfig]) => {
    buildService(serviceName, serviceConfig, tmpDir, authStrategy);
  });

  console.log(`Build complete for Microservices in ${tmpDir}`);
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