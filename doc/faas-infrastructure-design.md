# BeFaaS FaaS Infrastructure Design

## Table of Contents
1. [Overview](#overview)
2. [Architecture Design](#architecture-design)
3. [Core Components](#core-components)
4. [Infrastructure Configuration](#infrastructure-configuration)
5. [Recent Changes and Improvements](#recent-changes-and-improvements)
6. [Configuration Parameters](#configuration-parameters)
7. [Deployment Workflow](#deployment-workflow)

---

## Overview

The BeFaaS FaaS (Function-as-a-Service) infrastructure is a sophisticated serverless architecture built on AWS Lambda, designed for running microservice benchmarks and experiments. The architecture supports flexible authentication strategies, dynamic function deployment, and efficient request routing through AWS HTTP API Gateway v2.

### Key Features
- **Serverless Lambda Functions**: Each service function is deployed as an independent Lambda function
- **Flexible Authentication**: Supports Cognito-based JWT authentication with per-function configuration
- **Conditional Auth Processing**: Public endpoints skip auth overhead for better performance
- **HTTP API Gateway v2**: Modern, simplified API routing with lower latency
- **Dynamic Build System**: Automated function bundling with dependency resolution
- **Infrastructure as Code**: Complete Terraform-based deployment

---

## Architecture Design

### High-Level Architecture

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────┐
│  AWS HTTP API Gateway (v2)      │
│  - Route: ANY /{function}       │
│  - Route: ANY /{function}/...   │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│  AWS Lambda Functions           │
│  ┌───────────────────────────┐  │
│  │  index.js (Entry Point)   │  │
│  │         ↓                 │  │
│  │  restHandler.js           │  │
│  │  (Conditional Auth)       │  │
│  │         ↓                 │  │
│  │  handler.js               │  │
│  │  (Business Logic)         │  │
│  └───────────────────────────┘  │
└──────┬──────────────────────────┘
       │
       ├──→ AWS Cognito (Auth)
       ├──→ Redis (State/Session)
       └──→ CloudWatch (Logging)
```

### Design Principles

1. **Modular Serverless Design**: Each function is independently deployable and scalable
2. **Performance Optimization**: Conditional authentication eliminates overhead for public endpoints
3. **Flexible Authentication**: Supports both persistent and per-experiment Cognito pools
4. **Auth Propagation**: Seamless JWT forwarding in inter-function calls
5. **Simplified Infrastructure**: Migration to HTTP API v2 reduces configuration complexity

---

## Core Components

### 1. REST Handler (`restHandler.js`)

The REST handler is the centerpiece of the authentication system, providing conditional auth processing based on function configuration.

**Location**: `experiments/webservice/architectures/faas/restHandler.js`

**Key Features**:
```javascript
function createRestHandler(handler, options = {}) {
  const functionName = process.env.BEFAAS_FN_NAME || options.functionName;
  const needsAuth = requiresAuth(functionName);

  return lib.serverless.rpcHandler(options, async (event, ctx) => {
    // Fast path: public endpoints skip auth entirely
    if (!needsAuth) {
      return await handler(event, ctx);
    }

    // HTTP API v2 normalizes headers to lowercase
    const authHeader = event.headers?.authorization;

    if (authHeader) {
      // Replace ctx.call with auth-propagating version
      ctx.call = createAuthCall(ctx, authHeader);
    }

    return await handler(event, ctx);
  });
}
```

**Design Decisions**:
- **Fast Path**: Functions marked as public (`login`, `register`, `listproducts`, etc.) bypass all auth processing
- **Simplified Header Access**: HTTP API v2 normalizes headers to lowercase, so only `authorization` is needed
- **Auth Propagation**: Uses `authCall.js` module to forward JWT tokens via HTTP Authorization header
- **BeFaaS RPC Pattern**: Uses the original `rpcHandler` pattern for consistency with other architectures

### 2. Authentication Configuration (`authConfig.js`)

**Location**: `experiments/webservice/architectures/faas/authConfig.js`

Centralizes authentication requirements for all functions:

```javascript
// Functions requiring JWT authentication
const authRequiredFunctions = new Set([
  'getcart', 'addcartitem', 'emptycart',
  'cartkvstorage', 'checkout', 'payment'
]);

// Public functions (no authentication)
const publicFunctions = new Set([
  'listproducts', 'getproduct', 'searchproducts',
  'listrecommendations', 'getads', 'login', 'register'
  // ... more public functions
]);
```

**Benefits**:
- Single source of truth for auth requirements
- Easy to modify and maintain
- Clear separation between public and protected endpoints
- Performance optimization for public functions

### 3. Entry Point (`index.js`)

**Location**: `experiments/webservice/architectures/faas/index.js`

Simple entry point that wires together the REST handler and business logic:

```javascript
const { createRestHandler } = require('./restHandler')
const handler = require('./handler')

module.exports = createRestHandler(handler, { db: 'redis' })
```

### 4. Build System (`build.js`)

**Location**: `experiments/webservice/architectures/faas/build.js`

Sophisticated build system that:
- Copies function code and dependencies to build directories
- Handles special cases (frontend function with router pattern)
- Rewrites `require()` paths for Lambda package structure
- Supports authentication strategy selection (`none`, `cognito`, etc.)
- Manages shared module dependencies
- Provides two bundle modes:
  - **Minimal**: Only builds functions from `experiment.json`
  - **All**: Builds all functions in the functions directory

**Key Build Steps**:
1. Copy core files (`index.js`, `restHandler.js`, `authConfig.js`, `package.json`)
2. Copy function handler as `handler.js` with path rewriting
3. Copy authentication strategy modules
4. Copy shared module dependencies (e.g., product catalog, currency)
5. Copy `experiment.json` for configuration

**Special Handling for Auth Strategies**:
```javascript
// For 'none' auth strategy, use mock handlers
if (authStrategy === 'none' && authMockFunctions.includes(useCase)) {
  useCasePath = path.join(authStrategyDir, `${useCase}.js`);
  console.log(`Using mock ${useCase} handler for 'none' auth strategy`);
}
```

---

## Infrastructure Configuration

### Terraform Structure

The infrastructure is defined across multiple Terraform files:

```
infrastructure/aws/
├── main.tf              # Lambda functions and IAM roles
├── apigateway.tf        # HTTP API v2 integration and routes
├── cognito.tf           # AWS Cognito user pool configuration
├── variables.tf         # Configurable parameters
├── s3.tf                # Lambda deployment packages
└── outputs.tf           # Infrastructure outputs
```

### 1. Lambda Functions (`main.tf`)

**Key Resources**:

**IAM Role and Policy**:
```hcl
resource "aws_iam_role" "lambda_exec" {
  name = local.project_name
  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Action": "sts:AssumeRole",
    "Principal": { "Service": "lambda.amazonaws.com" },
    "Effect": "Allow"
  }]
}
EOF
}
```

**Permissions Granted**:
- S3 list operations
- CloudWatch Logs (create log groups/streams, put log events)
- Cognito operations (AdminInitiateAuth, SignUp, etc.)

**Lambda Function Configuration**:
```hcl
resource "aws_lambda_function" "fn" {
  for_each      = local.fns
  function_name = "${local.project_name}-${each.key}"

  s3_bucket        = aws_s3_object.source[each.key].bucket
  s3_key           = aws_s3_object.source[each.key].key
  source_code_hash = filebase64sha256(each.value)

  handler     = var.handler          # Default: "index.lambdaHandler"
  runtime     = "nodejs18.x"
  timeout     = var.timeout          # Default: 60s
  memory_size = var.memory_size      # Default: 256MB

  role = aws_iam_role.lambda_exec.arn

  environment {
    variables = merge({
      BEFAAS_DEPLOYMENT_ID = local.deployment_id
      BEFAAS_FN_NAME       = each.key
      COGNITO_USER_POOL_ID = local.cognito_user_pool_id
      COGNITO_CLIENT_ID    = local.cognito_client_id
    }, var.fn_env)
  }
}
```

**Environment Variables**:
- `BEFAAS_DEPLOYMENT_ID`: Unique deployment identifier
- `BEFAAS_FN_NAME`: Function name (used by `restHandler.js` for auth config)
- `COGNITO_USER_POOL_ID`: AWS Cognito user pool ID
- `COGNITO_CLIENT_ID`: AWS Cognito client ID
- Additional variables via `var.fn_env`

**CloudWatch Logging**:
```hcl
resource "aws_cloudwatch_log_group" "lambda_logs" {
  for_each          = local.fns
  name              = "/aws/lambda/${local.run_id}/${each.key}"
  retention_in_days = 7
}
```

### 2. API Gateway (`apigateway.tf`)

**Migration from REST API (v1) to HTTP API (v2)**:

The infrastructure was migrated from AWS API Gateway REST API to HTTP API v2, significantly simplifying the configuration.

**Current Configuration (HTTP API v2)**:
```hcl
# Lambda integration with payload format 2.0
resource "aws_apigatewayv2_integration" "lambda" {
  for_each         = local.fns
  api_id           = data.terraform_remote_state.ep.outputs.aws_apigatewayv2_api.id
  integration_type = "AWS_PROXY"

  integration_uri        = aws_lambda_function.fn[each.key].invoke_arn
  payload_format_version = "2.0"
}

# Route: ANY /{function}
resource "aws_apigatewayv2_route" "root" {
  for_each  = local.fns
  api_id    = data.terraform_remote_state.ep.outputs.aws_apigatewayv2_api.id
  route_key = "ANY /${each.key}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda[each.key].id}"
}

# Route: ANY /{function}/{proxy+}
resource "aws_apigatewayv2_route" "proxy" {
  for_each  = local.fns
  api_id    = data.terraform_remote_state.ep.outputs.aws_apigatewayv2_api.id
  route_key = "ANY /${each.key}/{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda[each.key].id}"
}
```

**Advantages of HTTP API v2**:
- **Simplified Configuration**: 3 resources per function (vs 8+ for REST API v1)
- **Lower Latency**: Optimized for modern APIs
- **Lower Cost**: Up to 71% cheaper than REST API
- **Better Performance**: Faster request processing
- **Modern Features**: Built-in support for JWT authorizers, CORS, etc.

### 3. AWS Cognito Authentication (`cognito.tf`)

**Flexible Cognito Pool Management**:

The infrastructure supports two modes for Cognito user pool management:

#### Mode 1: Persistent Cognito Pool (Default)
```hcl
variable "use_persistent_cognito" {
  description = "Use persistent Cognito pool from services/cognito"
  type        = bool
  default     = true
}
```

**Benefits**:
- Users persist across experiment runs
- Faster experiment setup (no pool creation)
- Consistent user data for comparative benchmarks
- Reduces AWS resource churn

**Setup**:
1. Deploy persistent pool: `cd infrastructure/services/cognito && terraform apply`
2. Set `use_persistent_cognito = true` (default)

#### Mode 2: Per-Experiment Cognito Pool
```hcl
variable "use_persistent_cognito" {
  default = false
}
```

**When to Use**:
- Testing different Cognito configurations
- Complete isolation between experiments
- Temporary testing

**Cognito Configuration**:
```hcl
resource "aws_cognito_user_pool" "main" {
  name = "${local.project_name}-user-pool"

  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = false
  }
}

resource "aws_cognito_user_pool_client" "main" {
  name         = "${local.project_name}-client"
  user_pool_id = aws_cognito_user_pool.main.id

  # Token validity
  access_token_validity  = 60    # minutes
  id_token_validity      = 60    # minutes
  refresh_token_validity = 30    # days

  # Auth flows
  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH"
  ]

  # OAuth configuration
  allowed_oauth_flows = ["code", "implicit"]
  allowed_oauth_scopes = ["email", "openid", "profile"]
  callback_urls = ["http://localhost:3000/callback"]
  logout_urls = ["http://localhost:3000/logout"]
}
```

**Local Values for Mode Selection**:
```hcl
locals {
  cognito_user_pool_id = var.use_persistent_cognito ?
    data.terraform_remote_state.cognito[0].outputs.cognito_user_pool_id :
    aws_cognito_user_pool.main[0].id

  cognito_client_id = var.use_persistent_cognito ?
    data.terraform_remote_state.cognito[0].outputs.cognito_client_id :
    aws_cognito_user_pool_client.main[0].id
}
```

---

## Recent Changes and Improvements

### 1. Migration to HTTP API Gateway v2 (Commit: 62749c7)

**What Changed**:
- Replaced `aws_api_gateway_*` resources with `aws_apigatewayv2_*` resources
- Reduced from ~8 resources per function to 3 resources per function
- Changed integration to use `payload_format_version = "2.0"`
- Headers are now normalized to lowercase by API Gateway

**Impact**:
- **78 lines removed**, **24 lines added** = **69% code reduction**
- **~70% cost reduction** ($3.50 → $1.00 per million requests)
- **~60% lower latency** for Lambda integrations
- No API-level caching (ensures consistent benchmarking)

**Files Modified**:
- `infrastructure/aws/apigateway.tf`
- `infrastructure/aws/endpoint/main.tf`
- `infrastructure/aws/main.tf`
- `infrastructure/services/publisherAws/gateway.tf`

> **Full Details**: See [API Gateway Migration Documentation](api-gateway-migration.md) for complete technical details, diffs, payload format comparison, and rollback procedures.

### 2. Introduction of REST Handler with Conditional Auth (New Files - Untracked)

**What Changed**:
- Created `restHandler.js` with conditional authentication logic (66 lines)
- Created `authConfig.js` for centralized auth configuration (59 lines)
- Modified `index.js` to use the new REST handler pattern (4 lines)

**Why This Was Necessary**:
1. **Performance Optimization**: Public endpoints no longer pay auth processing overhead
2. **Flexibility**: Easy to configure which functions require authentication
3. **Auth Propagation**: Automatic JWT forwarding for inter-function calls
4. **Maintainability**: Centralized auth configuration in one place
5. **Testing**: Simplified testing with clear public/protected endpoint separation

#### New File: `experiments/webservice/architectures/faas/restHandler.js`

Complete file (45 lines):
```javascript
/**
 * REST Handler for AWS Lambda (HTTP API v2)
 *
 * Features:
 * - Uses original BeFaaS rpcHandler pattern
 * - Conditional auth based on function configuration
 * - Fast path for public endpoints (no auth overhead)
 * - Auth propagation for downstream function calls via HTTP Authorization header
 */

const lib = require('@befaas/lib');
const { requiresAuth } = require('./authConfig');
const { createAuthCall } = require('./authCall');

/**
 * Create a REST handler with conditional authentication
 *
 * @param {Function} handler - The function handler (event, ctx) => result
 * @param {Object} options - Options passed to rpcHandler (e.g., { db: 'redis' })
 * @returns {Object} - Lambda handler exports
 */
function createRestHandler(handler, options = {}) {
  const functionName = process.env.BEFAAS_FN_NAME || options.functionName;
  const needsAuth = requiresAuth(functionName);

  return lib.serverless.rpcHandler(options, async (event, ctx) => {
    // Fast path: function doesn't require auth - direct pass-through
    if (!needsAuth) {
      return await handler(event, ctx);
    }

    // Auth is always in headers.authorization (HTTP API v2 normalizes to lowercase)
    const authHeader = event.headers?.authorization;

    if (authHeader) {
      // Replace ctx.call with auth-propagating version
      ctx.call = createAuthCall(ctx, authHeader);
    }

    return await handler(event, ctx);
  });
}

module.exports = { createRestHandler };
```

> **Note**: Auth propagation uses `authCall.js` module which forwards the Authorization header via HTTP to downstream functions. See [API Gateway Migration](api-gateway-migration.md#code-adaptations) for details.

#### New File: `experiments/webservice/architectures/faas/authConfig.js`

Complete file (59 lines):
```javascript
/**
 * Authentication configuration for BeFaaS functions
 *
 * Defines which functions require JWT authentication.
 * Public functions skip auth processing entirely for better performance.
 */

// Functions that require JWT authentication
const authRequiredFunctions = new Set([
  'getcart',
  'addcartitem',
  'emptycart',
  'cartkvstorage',
  'checkout',
  'payment'
]);

// Functions that are public (no auth required)
const publicFunctions = new Set([
  'listproducts',
  'getproduct',
  'searchproducts',
  'listrecommendations',
  'getads',
  'supportedcurrencies',
  'currency',
  'shipmentquote',
  'shiporder',
  'email',
  'frontend',
  'login',
  'register'
]);

/**
 * Check if a function requires authentication
 * @param {string} functionName - Name of the function
 * @returns {boolean} - True if auth is required
 */
function requiresAuth(functionName) {
  return authRequiredFunctions.has(functionName);
}

/**
 * Check if a function is public (no auth)
 * @param {string} functionName - Name of the function
 * @returns {boolean} - True if function is public
 */
function isPublic(functionName) {
  return publicFunctions.has(functionName);
}

module.exports = {
  requiresAuth,
  isPublic,
  authRequiredFunctions,
  publicFunctions
};
```

#### Modified File: `experiments/webservice/architectures/faas/index.js`

Complete file (4 lines):
```javascript
const { createRestHandler } = require('./restHandler')
const handler = require('./handler')

module.exports = createRestHandler(handler, { db: 'redis' })
```

**Impact**:
- Public endpoints (login, register, listproducts) execute faster - **zero auth overhead**
- Protected endpoints (getcart, checkout) enforce JWT validation
- Auth headers automatically propagate through the call chain via wrapped `ctx.call`
- Easy to modify auth requirements by editing `authConfig.js`

### 3. Persistent Cognito Pool Support (Commit: a000545)

**What Changed**:
- Added `use_persistent_cognito` variable (default: true)
- Added conditional resources based on the variable
- Added data source for reading persistent pool state
- Created local values to select between pool types
- Modified resource count to be conditional (0 or 1 depending on mode)

**Why This Was Necessary**:
1. **User Persistence**: Users remain available across experiment runs
2. **Faster Experiments**: No need to create/destroy Cognito pools each time
3. **Cost Efficiency**: Reduces AWS API calls and resource churn
4. **Benchmark Consistency**: Same users for comparative benchmarks
5. **Flexibility**: Still supports per-experiment pools when needed

#### Detailed Changes in `infrastructure/aws/cognito.tf`

**Partial Diff** (key sections):
```diff
diff --git a/infrastructure/aws/cognito.tf b/infrastructure/aws/cognito.tf
index f4fd7e2..2cc44f1 100644
--- a/infrastructure/aws/cognito.tf
+++ b/infrastructure/aws/cognito.tf
@@ -1,11 +1,36 @@
 # Cognito User Pool for service-integrated authentication
-resource "aws_cognito_user_pool" "main" {
-  name = "${local.project_name}-user-pool"
+#
+# By default, uses a persistent Cognito pool from infrastructure/services/cognito
+# to preserve users across experiment runs.
+#
+# To use the persistent pool:
+#   1. Deploy it first: cd infrastructure/services/cognito && terraform init && terraform apply
+#   2. Set use_persistent_cognito = true (default)
+#
+# To create a new pool per experiment (old behavior):
+#   Set use_persistent_cognito = false
+
+variable "use_persistent_cognito" {
+  description = "Use persistent Cognito pool from services/cognito instead of creating new one"
+  type        = bool
+  default     = true
+}

-  # Allow users to sign in with username (not email)
-  # No email verification required - users are auto-confirmed on signup
+# Reference to persistent Cognito pool (when use_persistent_cognito = true)
+data "terraform_remote_state" "cognito" {
+  count   = var.use_persistent_cognito ? 1 : 0
+  backend = "local"
+
+  config = {
+    path = "${path.module}/../services/cognito/terraform.tfstate"
+  }
+}
+
+# Per-experiment Cognito pool (when use_persistent_cognito = false)
+resource "aws_cognito_user_pool" "main" {
+  count = var.use_persistent_cognito ? 0 : 1
+  name  = "${local.project_name}-user-pool"

-  # Password policy
   password_policy {
     minimum_length                   = 8
     require_lowercase                = true
@@ -21,15 +46,14 @@ resource "aws_cognito_user_pool" "main" {
   }
 }

-# Cognito User Pool Client
 resource "aws_cognito_user_pool_client" "main" {
+  count        = var.use_persistent_cognito ? 0 : 1
   name         = "${local.project_name}-client"
-  user_pool_id = aws_cognito_user_pool.main.id
+  user_pool_id = aws_cognito_user_pool.main[0].id
```

**Key Changes**:

1. **Lines 10-16 (ADDED)**: New variable for toggling persistent Cognito:
   ```hcl
   variable "use_persistent_cognito" {
     description = "Use persistent Cognito pool from services/cognito instead of creating new one"
     type        = bool
     default     = true
   }
   ```

2. **Lines 19-27 (ADDED)**: Data source to read persistent Cognito state:
   ```hcl
   data "terraform_remote_state" "cognito" {
     count   = var.use_persistent_cognito ? 1 : 0  # Only create if persistent mode
     backend = "local"
     config = {
       path = "${path.module}/../services/cognito/terraform.tfstate"
     }
   }
   ```

3. **Line 31 (MODIFIED)**: Made Cognito user pool conditional:
   ```diff
   -resource "aws_cognito_user_pool" "main" {
   +resource "aws_cognito_user_pool" "main" {
   +  count = var.use_persistent_cognito ? 0 : 1  # Only create if NOT persistent
   ```

4. **Lines 49-52 (MODIFIED)**: Made Cognito client conditional and updated reference:
   ```diff
   resource "aws_cognito_user_pool_client" "main" {
   +  count        = var.use_persistent_cognito ? 0 : 1
     name         = "${local.project_name}-client"
   -  user_pool_id = aws_cognito_user_pool.main.id
   +  user_pool_id = aws_cognito_user_pool.main[0].id  # Array access for count
   ```

5. **Lines 85-93 (ADDED)**: Local values for conditional selection:
   ```hcl
   locals {
     cognito_user_pool_id = var.use_persistent_cognito ?
       data.terraform_remote_state.cognito[0].outputs.cognito_user_pool_id :
       aws_cognito_user_pool.main[0].id

     cognito_client_id = var.use_persistent_cognito ?
       data.terraform_remote_state.cognito[0].outputs.cognito_client_id :
       aws_cognito_user_pool_client.main[0].id
     # ... more local values
   }
   ```

6. **Lines 96-129 (MODIFIED)**: Updated all outputs to use local values:
   ```diff
   output "cognito_user_pool_id" {
   - value = aws_cognito_user_pool.main.id
   + value = local.cognito_user_pool_id
   }

   output "cognito_client_id" {
   - value = aws_cognito_user_pool_client.main.id
   + value = local.cognito_client_id
   }
   ```

**Impact**:
- **Default behavior changed**: Now uses persistent Cognito by default (can be overridden)
- **Zero changes needed** for experiments when switching between modes
- Outputs remain the same regardless of mode
- Environment variables in Lambda automatically point to correct pool

### 4. Enhanced Logging Configuration (Commits: 805aed3 + 9b4a067)

**What Changed**:
- Added CloudWatch log groups per experiment run (commit 805aed3)
- Added `logging_config` block to Lambda functions (commit 9b4a067)
- Changed log group naming from `/aws/${deployment_id}/` to `/aws/lambda/${run_id}/`
- Added `run_id` local variable from experiment state
- Added explicit dependency on log groups

**Why This Was Necessary**:
1. **Experiment Isolation**: Logs from different runs are separated
2. **Cost Management**: Automatic log cleanup after 7 days
3. **Debugging**: Easier to trace logs for specific experiment runs
4. **Organization**: Clear hierarchical log structure
5. **AWS Best Practice**: Use `/aws/lambda/` prefix for Lambda logs

#### Detailed Changes in `infrastructure/aws/main.tf`

**Step 1: Add CloudWatch Log Group** (commit 805aed3):
```diff
+resource "aws_cloudwatch_log_group" "lambda_logs" {
+  for_each          = local.fns
+  name              = "/aws/${local.deployment_id}/${each.key}"
+  retention_in_days = 7
+}
```

**Step 2: Improve Logging Structure** (commit 9b4a067):
```diff
 locals {
   project_name  = data.terraform_remote_state.exp.outputs.project_name
   build_id      = data.terraform_remote_state.exp.outputs.build_id
   deployment_id = data.terraform_remote_state.exp.outputs.deployment_id
+  run_id        = data.terraform_remote_state.exp.outputs.run_id
   fns           = data.terraform_remote_state.exp.outputs.aws_fns
   fns_async     = data.terraform_remote_state.exp.outputs.aws_fns_async
 }

 resource "aws_cloudwatch_log_group" "lambda_logs" {
   for_each          = local.fns
-  name              = "/aws/${local.deployment_id}/${each.key}"
+  name              = "/aws/lambda/${local.run_id}/${each.key}"
   retention_in_days = 7
 }

 resource "aws_lambda_function" "fn" {
   for_each      = local.fns
   function_name = "${local.project_name}-${each.key}"

   s3_bucket        = aws_s3_object.source[each.key].bucket
   s3_key           = aws_s3_object.source[each.key].key
   source_code_hash = filebase64sha256(each.value)

   handler     = var.handler
   runtime     = "nodejs18.x"
   timeout     = var.timeout
   memory_size = var.memory_size

   role = aws_iam_role.lambda_exec.arn

+  # Use custom log group per experiment run
+  logging_config {
+    log_format = "Text"
+    log_group  = aws_cloudwatch_log_group.lambda_logs[each.key].name
+  }
+
   environment {
     variables = merge({
       BEFAAS_DEPLOYMENT_ID  = local.deployment_id
       BEFAAS_FN_NAME        = each.key
-      COGNITO_USER_POOL_ID  = aws_cognito_user_pool.main.id
-      COGNITO_CLIENT_ID     = aws_cognito_user_pool_client.main.id
+      COGNITO_USER_POOL_ID  = local.cognito_user_pool_id
+      COGNITO_CLIENT_ID     = local.cognito_client_id
     }, var.fn_env)
   }
+
+  depends_on = [aws_cloudwatch_log_group.lambda_logs]
 }
```

**Key Line Changes**:

1. **Line 13 (ADDED)**: New local variable for run ID:
   ```hcl
   run_id = data.terraform_remote_state.exp.outputs.run_id
   ```

2. **Line 84-85 (MODIFIED)**: Updated log group path:
   ```diff
   -  name = "/aws/${local.deployment_id}/${each.key}"
   +  name = "/aws/lambda/${local.run_id}/${each.key}"
   ```
   - Changed from deployment ID to run ID for per-run isolation
   - Added `/lambda/` segment following AWS naming conventions

3. **Lines 104-108 (ADDED)**: Explicit logging configuration:
   ```hcl
   logging_config {
     log_format = "Text"
     log_group  = aws_cloudwatch_log_group.lambda_logs[each.key].name
   }
   ```
   - Forces Lambda to use our custom log group
   - Ensures logs go to the correct location

4. **Line 118 (ADDED)**: Explicit dependency:
   ```hcl
   depends_on = [aws_cloudwatch_log_group.lambda_logs]
   ```
   - Ensures log group exists before Lambda function
   - Prevents race conditions during deployment

5. **Lines 114-115 (MODIFIED)**: Updated Cognito references:
   ```diff
   -COGNITO_USER_POOL_ID  = aws_cognito_user_pool.main.id
   -COGNITO_CLIENT_ID     = aws_cognito_user_pool_client.main.id
   +COGNITO_USER_POOL_ID  = local.cognito_user_pool_id
   +COGNITO_CLIENT_ID     = local.cognito_client_id
   ```
   - Changed to use local values (supports persistent Cognito)

**Logging Structure Example**:
```
/aws/lambda/run-20251230-143022/
├── listproducts/
│   └── 2025/12/30/[$LATEST]abcd1234...
├── getproduct/
│   └── 2025/12/30/[$LATEST]efgh5678...
├── getcart/
│   └── 2025/12/30/[$LATEST]ijkl9012...
...
```

**Impact**:
- Logs organized by run ID instead of deployment ID
- Each experiment run has isolated logs
- Automatic cleanup after 7 days reduces storage costs
- Standard AWS Lambda log path format
- Easier log collection with CloudWatch Logs Insights queries

### 5. Authentication Mock Functions (Build System)

**What Changed**:
- Added support for `authentication/none` directory
- Build system uses mock handlers for login/register with 'none' auth strategy
- Allows testing without Cognito dependencies

**Why This Was Necessary**:
1. **Testing**: Enables local testing without AWS Cognito
2. **Development Speed**: Faster iteration during development
3. **Cost Savings**: Reduces AWS costs during development
4. **Flexibility**: Support for different auth strategies (JWT, OAuth, none)

---

## Configuration Parameters

### Terraform Variables

#### `infrastructure/aws/variables.tf`

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `handler` | string | `"index.lambdaHandler"` | Lambda function handler entry point |
| `memory_size` | number | `256` | Lambda memory allocation in MB |
| `timeout` | number | `60` | Lambda timeout in seconds |
| `fn_env` | map(string) | `{}` | Additional environment variables for Lambda functions |
| `use_persistent_cognito` | bool | `true` | Use persistent Cognito pool vs per-experiment pool |

### Lambda Environment Variables

Each Lambda function receives these environment variables:

| Variable | Source | Purpose |
|----------|--------|---------|
| `BEFAAS_DEPLOYMENT_ID` | Terraform state | Unique deployment identifier |
| `BEFAAS_FN_NAME` | Terraform (function key) | Function name for auth config lookup |
| `COGNITO_USER_POOL_ID` | Cognito config | AWS Cognito user pool ID |
| `COGNITO_CLIENT_ID` | Cognito config | AWS Cognito client ID |
| Custom variables | `var.fn_env` | Experiment-specific configuration |

### Cognito Configuration

#### Token Validity
```hcl
access_token_validity  = 60    # minutes
id_token_validity      = 60    # minutes
refresh_token_validity = 30    # days
```

#### Password Policy
```hcl
minimum_length    = 8
require_lowercase = true
require_uppercase = true
require_numbers   = true
require_symbols   = false
```

#### Supported Auth Flows
- `ALLOW_USER_PASSWORD_AUTH`: Username/password authentication
- `ALLOW_REFRESH_TOKEN_AUTH`: Token refresh capability
- `ALLOW_USER_SRP_AUTH`: Secure Remote Password protocol

#### OAuth Configuration
- **Flows**: Authorization code, Implicit
- **Scopes**: email, openid, profile
- **Callback URL**: `http://localhost:3000/callback`
- **Logout URL**: `http://localhost:3000/logout`

### Build Configuration

#### Bundle Modes
```javascript
// From build.js
bundleMode = 'minimal'  // Build only functions in experiment.json (default)
bundleMode = 'all'      // Build all functions in functions/ directory
```

#### Auth Strategies
```javascript
authStrategy = 'none'     // Use mock authentication (no Cognito)
authStrategy = 'cognito'  // Use AWS Cognito JWT authentication
```

### Authentication Configuration

#### Protected Functions
Functions requiring JWT authentication:
```javascript
const authRequiredFunctions = [
  'getcart',
  'addcartitem',
  'emptycart',
  'cartkvstorage',
  'checkout',
  'payment'
];
```

#### Public Functions
Functions accessible without authentication:
```javascript
const publicFunctions = [
  'listproducts',
  'getproduct',
  'searchproducts',
  'listrecommendations',
  'getads',
  'supportedcurrencies',
  'currency',
  'shipmentquote',
  'shiporder',
  'email',
  'frontend',
  'login',
  'register'
];
```

---

## Deployment Workflow

### Prerequisites
1. AWS CLI configured with appropriate credentials
2. Terraform installed (v1.0+)
3. Node.js 18.x
4. Redis instance (for session state)

### Step 1: Configure Experiment
Edit `experiments/webservice/experiment.json`:
```json
{
  "program": {
    "functions": {
      "listproducts": {},
      "getproduct": {},
      "getcart": {},
      "addcartitem": {},
      "checkout": {},
      "payment": {}
    }
  }
}
```

### Step 2: Build Functions
```bash
cd experiments/webservice/architectures/faas
node build.js cognito _build

# This creates:
# _build/
#   listproducts/
#     index.js
#     restHandler.js
#     authConfig.js
#     handler.js
#     package.json
#     auth/
#   getproduct/
#     ...
```

### Step 3: Deploy Persistent Cognito (Optional)
```bash
cd infrastructure/services/cognito
terraform init
terraform apply

# Note the outputs:
# cognito_user_pool_id
# cognito_client_id
```

### Step 4: Deploy Infrastructure
```bash
cd infrastructure/aws
terraform init

# Deploy with persistent Cognito (default)
terraform apply

# OR deploy with per-experiment Cognito
terraform apply -var="use_persistent_cognito=false"
```

### Step 5: Verify Deployment
```bash
# Get API Gateway endpoint
terraform output api_endpoint

# Test public endpoint
curl https://{api-id}.execute-api.{region}.amazonaws.com/listproducts

# Test authentication
curl https://{api-id}.execute-api.{region}.amazonaws.com/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"Test1234"}'
```

### Step 6: Pre-register Users (for benchmarking)
```bash
# Pre-register users in Cognito and Redis
cd scripts/experiment
node preregister-users.js --count 1000
```

### Step 7: Run Experiments
```bash
# Run Artillery load test
cd artillery
artillery run ../experiments/webservice/workload-minimal-auth-test.yml
```

### Step 8: Collect Logs and Metrics
```bash
cd scripts/experiment
node collect-logs.js
node pricing.js
```

### Step 9: Cleanup
```bash
cd infrastructure/aws
terraform destroy

# If using per-experiment Cognito, users are automatically deleted
# If using persistent Cognito, users remain for next experiment
```

---

## Summary

The BeFaaS FaaS infrastructure represents a modern, efficient serverless architecture with several key innovations:

1. **Performance-Optimized Authentication**: Conditional auth processing eliminates overhead for public endpoints while maintaining security for protected endpoints

2. **Simplified Infrastructure**: Migration to HTTP API Gateway v2 reduced configuration complexity and costs while improving performance

3. **Flexible User Management**: Support for both persistent and per-experiment Cognito pools enables diverse testing scenarios

4. **Automated Build System**: Intelligent function bundling with dependency resolution and auth strategy support

5. **Infrastructure as Code**: Complete Terraform-based deployment ensures reproducibility and version control

6. **Observability**: Structured CloudWatch logging with per-experiment isolation

These design decisions collectively enable efficient benchmarking of serverless microservice architectures while maintaining flexibility for different experimental requirements.