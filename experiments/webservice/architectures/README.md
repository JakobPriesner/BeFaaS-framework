
# Directory Structure

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
