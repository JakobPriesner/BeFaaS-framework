# Architecture Build System

This directory contains the implementation of different architectural patterns for the webservice experiment. Each architecture is self-contained and can be built, deployed, and benchmarked independently.

## Directory Structure

```
architectures/
├── faas/               # Function-as-a-Service architecture
│   ├── index.js        # FaaS wrapper that calls handler
│   ├── build.js        # Build logic for FaaS
│   └── package.json    # Dependencies for FaaS functions
├── microservices/      # Microservices architecture
│   ├── build.js        # Build logic for microservices
│   ├── shared/         # Shared utilities (service discovery)
│   └── *-service/      # Individual microservice implementations
├── monolith/           # Monolithic architecture
│   ├── index.js        # Main monolith application
│   ├── build.js        # Build logic for monolith
│   ├── package.json    # Dependencies for monolith
│   └── Dockerfile      # Container definition
└── shared/             # Shared build utilities
    └── buildUtils.js   # Common build functions (bundling, zipping, etc.)
```

## Architecture-Specific Build Files

Each architecture has its own `build.js` file that contains **architecture-specific** logic:

- **What to include**: Which files to copy, how to structure the output
- **Not responsible for**: Bundling, zipping, Docker builds (use `buildUtils.js` for that)

### Build Function Signature

```javascript
function build(tmpDir, authStrategy) {
  // Copy architecture-specific files to tmpDir
  // Copy required functions from experiments/webservice/functions
  // Copy auth strategy from experiments/webservice/authentication
}

module.exports = build;
```

## Build Utilities (shared/buildUtils.js)

Common build operations that all architectures can use:

- `bundleAndZip(sourceDir, outputZip, options)` - Bundle with ncc and create zip
- `installDependencies(dir, production)` - Install npm dependencies
- `buildDockerImage(serviceDir, imageName, tag)` - Build Docker image
- `pushDockerImage(imageName, tag)` - Push to Docker registry
- `createZip(sourceDir, outputZip)` - Create zip without bundling
- `cleanDirectory(dir)` - Clean and recreate directory

## Running Experiments

Use the unified experiment script to build, deploy, and benchmark:

```bash
# Full experiment with FaaS architecture
node scripts/experiment.js --architecture faas --auth none

# Build and deploy microservices
node scripts/experiment.js -a microservices -u service-integrated --skip-benchmark

# Only build monolith
node scripts/experiment.js -a monolith -u none --build-only
```

### Available Options

- `--architecture, -a` - Architecture type (faas, microservices, monolith)
- `--auth, -u` - Authentication strategy (none, service-integrated)
- `--build-only` - Only build, don't deploy
- `--deploy-only` - Only deploy (skip build)
- `--skip-benchmark` - Skip benchmark execution
- `--skip-metrics` - Skip metrics collection
- `--workload` - Workload file (default: workload-constant.yml)
- `--output-dir` - Output directory for results

## Architecture Details

### FaaS (Function-as-a-Service)

Each function is deployed independently as a serverless function.

**Build Output Structure:**
```
_build/
├── <function-name>/
│   ├── index.js        # FaaS wrapper
│   ├── handler.js      # Business logic
│   ├── auth/           # Authentication module
│   └── package.json
```

**Deployment:** Uses existing Terraform infrastructure for AWS Lambda, Azure Functions, Google Cloud Functions, etc.

### Microservices

Functions are grouped into services, each running as an independent container.

**Build Output Structure:**
```
_build/
├── cart-service/
│   ├── index.js
│   ├── functions/      # Multiple function handlers
│   ├── auth/
│   ├── shared/
│   └── package.json
├── product-service/
└── ...
```

**Services:**
- `cart-service` - Cart management (getcart, addcartitem, emptycart, cartkvstorage)
- `content-service` - Content delivery (getads, supportedcurrencies, currency)
- `frontend-service` - Frontend rendering
- `order-service` - Order processing (checkout, payment, shipmentquote, email)
- `product-service` - Product catalog (getproduct, listproducts, searchproducts, listrecommendations)

**Deployment:** Uses Docker Compose with service discovery

### Monolith

All functions are bundled into a single application.

**Build Output Structure:**
```
_build/
├── index.js
├── functions/          # All function handlers
│   ├── getcart/
│   ├── addcartitem/
│   └── ...
├── auth/
├── package.json
└── Dockerfile
```

**Deployment:** Single Docker container or direct deployment

## Authentication Strategies

Authentication modules are copied from `experiments/webservice/authentication/`:

- **none** - No authentication, always returns true
- **service-integrated** - JWT-based authentication integrated into the service

The authentication module is included in each built artifact and provides a `verifyJWT(event)` function.

## Adding a New Architecture

1. Create a new directory under `architectures/<architecture-name>/`
2. Create `build.js` with the build function
3. Create `index.js` with the architecture-specific runtime code
4. Create `package.json` with dependencies
5. Update `scripts/experiment.js` to support the new architecture
6. Document the architecture in this README

## Development Workflow

1. **Develop functions** in `experiments/webservice/functions/<function-name>/`
   - Only implement the handler logic
   - Use `ctx.call()` for inter-function communication
   - Keep dependencies minimal

2. **Build architecture**
   ```bash
   node scripts/experiment.js -a <architecture> -u <auth> --build-only
   ```

3. **Test locally**
   - For monolith/microservices: Use Docker Compose
   - For FaaS: Use local FaaS emulators

4. **Deploy and benchmark**
   ```bash
   node scripts/experiment.js -a <architecture> -u <auth>
   ```

5. **Analyze results**
   - Results are saved in `results/<architecture>-<auth>-<timestamp>/`
   - Includes metrics, benchmark results, and analysis

## Comparison with Old Build System

### Old System (scripts/build.sh)
- Uses ncc to bundle everything
- Creates ZIPs for Terraform deployment
- Tightly coupled to experiment.json
- Hard to test individual architectures

### New System (architecture-specific build.js)
- Separation of concerns: architecture logic vs build utilities
- Modular and testable
- Easy to add new architectures
- Supports multiple deployment targets
- Clear dependency management

## Future Enhancements

- [ ] Integrate with existing Terraform deployment
- [ ] Add support for Kubernetes deployment
- [ ] Implement automated benchmark comparison
- [ ] Add CI/CD pipeline integration
- [ ] Support for custom dependency versions per architecture
- [ ] Automated dependency detection and optimization