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
      ioredis: '^5.3.2',
      'aws-sdk': '^2.1400.0',
      'aws-jwt-verify': '^4.0.0',
      axios: '^1.4.0'
    },
    port: 3002
  },
  'content-service': {
    functions: ['getads', 'supportedcurrencies', 'currency'],
    copyCurrencyModule: true, // Need currency/exchangerates.js for currency functions
    dependencies: {
      '@befaas/lib': '*',
      express: '^4.18.2',
      'aws-sdk': '^2.1400.0',
      axios: '^1.4.0'
    },
    port: 3004
  },
  'frontend-service': {
    // Note: frontend-service uses handlers.js directly, not the FaaS frontend function
    functions: ['login', 'register'],
    copyFrontendHandlers: true, // Special flag to copy frontend handlers and templates
    dependencies: {
      '@befaas/lib': '*',
      express: '^4.18.2',
      'cookie-parser': '^1.4.6',
      lodash: '^4.17.21',
      nunjucks: '^3.2.4',
      'aws-sdk': '^2.1400.0',
      '@aws-sdk/client-cognito-identity-provider': '^3.400.0',
      axios: '^1.4.0'
    },
    port: 3000
  },
  'order-service': {
    functions: ['checkout', 'payment', 'shipmentquote', 'shiporder', 'email'],
    dependencies: {
      '@befaas/lib': '*',
      express: '^4.18.2',
      'aws-sdk': '^2.1400.0',
      'aws-jwt-verify': '^4.0.0',
      'card-validator': '^8.1.1',
      axios: '^1.4.0'
    },
    port: 3003
  },
  'product-service': {
    functions: ['getproduct', 'listproducts', 'searchproducts', 'listrecommendations'],
    copyProductCatalog: true, // Need productcatalog/products.js for product functions
    dependencies: {
      '@befaas/lib': '*',
      express: '^4.18.2',
      lodash: '^4.17.21',
      'aws-sdk': '^2.1400.0',
      axios: '^1.4.0'
    },
    port: 3001
  }
};

function copyFunctionToService(functionName, serviceDir, authStrategy) {
  const functionsDir = path.join(serviceDir, 'functions');
  const functionDir = path.join(functionsDir, functionName);

  if (!fs.existsSync(functionDir)) {
    fs.mkdirSync(functionDir, { recursive: true });
  }

  // Functions that should use mock handlers in 'none' auth mode
  const authMockFunctions = ['login', 'register'];
  const authStrategyDir = path.join(__dirname, '..', '..', 'authentication', authStrategy);

  let srcPath;
  // For 'none' auth strategy, use mock handlers for login and register to skip Cognito calls
  if (authStrategy === 'none' && authMockFunctions.includes(functionName)) {
    const mockHandlerPath = path.join(authStrategyDir, `${functionName}.js`);
    if (fs.existsSync(mockHandlerPath)) {
      srcPath = mockHandlerPath;
      console.log(`    Using mock ${functionName} handler for 'none' auth strategy`);
    } else {
      srcPath = path.join(__dirname, '..', '..', 'functions', functionName, 'index.js');
    }
  } else {
    srcPath = path.join(__dirname, '..', '..', 'functions', functionName, 'index.js');
  }

  const destPath = path.join(functionDir, 'index.js');

  // Copy function file as-is (like monolith does)
  // @befaas/lib is included in dependencies so require works
  fs.copyFileSync(srcPath, destPath);

  // Read content to check for auth requirement
  const content = fs.readFileSync(srcPath, 'utf8');

  // Copy auth file directly into function directory (functions require './auth')
  if (content.includes("require('./auth')")) {
    const authSrcDir = path.join(__dirname, '..', '..', 'authentication', authStrategy);
    const authSrcFile = path.join(authSrcDir, 'index.js');
    const authDestFile = path.join(functionDir, 'auth.js');
    if (fs.existsSync(authSrcFile)) {
      fs.copyFileSync(authSrcFile, authDestFile);
    }
  }
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

function copyCurrencyModule(serviceDir) {
  // Copy shared currency module (exchangerates.js) for services that need it
  // The currency functions require '../../currency/exchangerates' relative to functions/currency/
  const currencySrcDir = path.join(__dirname, '..', '..', 'currency');
  const currencyDestDir = path.join(serviceDir, 'currency');

  if (!fs.existsSync(currencyDestDir)) {
    fs.mkdirSync(currencyDestDir, { recursive: true });
  }

  const exchangeRatesSrc = path.join(currencySrcDir, 'exchangerates.js');
  const exchangeRatesDest = path.join(currencyDestDir, 'exchangerates.js');

  if (fs.existsSync(exchangeRatesSrc)) {
    fs.copyFileSync(exchangeRatesSrc, exchangeRatesDest);
    console.log(`    Copied currency/exchangerates.js`);
  }
}

function copyProductCatalog(serviceDir) {
  // Copy productcatalog/products.js for product-service
  // Functions require '../../productcatalog/products' from functions/functionName/
  const productSrcDir = path.join(__dirname, '..', '..', 'productcatalog');
  const productDestDir = path.join(serviceDir, 'productcatalog');

  if (!fs.existsSync(productDestDir)) {
    fs.mkdirSync(productDestDir, { recursive: true });
  }

  const productsSrc = path.join(productSrcDir, 'products.js');
  const productsDest = path.join(productDestDir, 'products.js');

  if (fs.existsSync(productsSrc)) {
    fs.copyFileSync(productsSrc, productsDest);
    console.log(`    Copied productcatalog/products.js`);
  }
}

function copyFrontendHandlers(serviceDir) {
  // Copy frontend handlers.js and html_templates for frontend-service
  const frontendSrcDir = path.join(__dirname, '..', '..', 'functions', 'frontend');
  const frontendDestDir = path.join(serviceDir, 'functions', 'frontend');

  if (!fs.existsSync(frontendDestDir)) {
    fs.mkdirSync(frontendDestDir, { recursive: true });
  }

  // Copy handlers.js as-is (like monolith does)
  // @befaas/lib is included in dependencies so require works
  const handlersSrc = path.join(frontendSrcDir, 'handlers.js');
  const handlersDest = path.join(frontendDestDir, 'handlers.js');
  fs.copyFileSync(handlersSrc, handlersDest);

  // Copy html_templates directory
  const templatesSrcDir = path.join(frontendSrcDir, 'html_templates');
  const templatesDestDir = path.join(frontendDestDir, 'html_templates');

  if (!fs.existsSync(templatesDestDir)) {
    fs.mkdirSync(templatesDestDir, { recursive: true });
  }

  const templateFiles = fs.readdirSync(templatesSrcDir);
  templateFiles.forEach(file => {
    const srcPath = path.join(templatesSrcDir, file);
    const destPath = path.join(templatesDestDir, file);
    if (fs.statSync(srcPath).isFile()) {
      fs.copyFileSync(srcPath, destPath);
    }
  });

  console.log(`    Copied frontend handlers and templates`);
}

function copyDockerfile(serviceName, serviceDir) {
  const dockerfileSrc = path.join(__dirname, serviceName, 'Dockerfile');
  const dockerfileDest = path.join(serviceDir, 'Dockerfile');

  if (fs.existsSync(dockerfileSrc)) {
    fs.copyFileSync(dockerfileSrc, dockerfileDest);
  } else {
    // Create a default Dockerfile if one doesn't exist
    const defaultDockerfile = `# Multi-stage build for ${serviceName}
FROM node:18-alpine AS base

# Build stage
FROM base AS builder
WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --only=production

# Runtime stage
FROM base AS runner
WORKDIR /app

# Install curl for healthchecks
RUN apk add --no-cache curl

# Copy dependencies from builder
COPY --from=builder /app/node_modules ./node_modules

# Copy service code
COPY . .

# Set environment variables
ENV NODE_ENV=production
ENV PORT=${services[serviceName].port}

# Expose service port
EXPOSE ${services[serviceName].port}

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \\
  CMD curl -f http://localhost:${services[serviceName].port}/health || exit 1

# Start the service
CMD ["node", "index.js"]
`;
    fs.writeFileSync(dockerfileDest, defaultDockerfile);
  }
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

  // Copy Dockerfile
  copyDockerfile(serviceName, serviceDir);

  // Copy all functions for this service
  serviceConfig.functions.forEach(functionName => {
    copyFunctionToService(functionName, serviceDir, authStrategy);
  });

  // Copy frontend handlers and templates if needed (for frontend-service)
  if (serviceConfig.copyFrontendHandlers) {
    copyFrontendHandlers(serviceDir);
  }

  // Copy currency module if needed (for content-service)
  if (serviceConfig.copyCurrencyModule) {
    copyCurrencyModule(serviceDir);
  }

  // Copy product catalog if needed (for product-service)
  if (serviceConfig.copyProductCatalog) {
    copyProductCatalog(serviceDir);
  }

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