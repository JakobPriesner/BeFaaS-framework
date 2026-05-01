# AWS API Gateway Migration: REST API (v1) to HTTP API (v2)

## Table of Contents
1. [Overview](#overview)
2. [Decision Rationale](#decision-rationale)
3. [Technical Comparison](#technical-comparison)
4. [Payload Format v2.0](#payload-format-v20)
5. [Infrastructure Changes](#infrastructure-changes)
6. [Code Adaptations](#code-adaptations)
7. [Testing and Validation](#testing-and-validation)
8. [Rollback Plan](#rollback-plan)

---

## Overview

This document describes the migration from AWS API Gateway REST API (v1) to HTTP API (v2) in the BeFaaS framework, completed on **2024-12-22** (commit `62749c7`).

### Summary

| Metric | Before (REST API) | After (HTTP API) |
|--------|-------------------|------------------|
| Resources per function | 8 | 3 |
| Lines of Terraform | 78 | 24 |
| Cost | $3.50/million requests | $1.00/million requests |
| Latency | Higher | ~60% lower |
| Caching | Available (unused) | Not available |

---

## Decision Rationale

### Why Migrate?

1. **Cost Reduction**: HTTP API is ~70% cheaper than REST API
2. **Lower Latency**: Optimized for Lambda integrations with faster request processing
3. **Simpler Configuration**: Fewer Terraform resources to manage (8 → 3 per function)
4. **Modern Standards**: HTTP API is AWS's recommended solution for new APIs
5. **Better Scaling**: Improved auto-scaling behavior under load
6. **No Unwanted Caching**: HTTP API doesn't support API-level caching, ensuring consistent benchmarking

### Why Not Migrate?

These features are NOT needed by BeFaaS, making HTTP API a clear choice:

| REST API Feature | Needed? | Notes |
|------------------|---------|-------|
| API caching | No | Would skew benchmark results |
| Usage plans/API keys | No | Not using rate limiting |
| Request validation | No | Handled in Lambda |
| AWS WAF integration | No | Not required for benchmarking |
| Private APIs | No | Using public endpoints |

---

## Technical Comparison

### Architecture Differences

```
REST API (v1) Structure:
┌─────────────────────────────────────────────┐
│ aws_api_gateway_rest_api                    │
│   └── aws_api_gateway_resource (/{fn})      │
│         ├── aws_api_gateway_method (ANY)    │
│         ├── aws_api_gateway_integration     │
│         └── aws_api_gateway_resource        │
│               └── ({proxy+})                │
│                     ├── method              │
│                     └── integration         │
│   └── aws_api_gateway_deployment            │
│         └── aws_api_gateway_stage           │
└─────────────────────────────────────────────┘

HTTP API (v2) Structure:
┌─────────────────────────────────────────────┐
│ aws_apigatewayv2_api                        │
│   └── aws_apigatewayv2_stage ($default)     │
│         └── auto_deploy = true              │
│   └── aws_apigatewayv2_integration          │
│   └── aws_apigatewayv2_route (ANY /{fn})    │
│   └── aws_apigatewayv2_route (ANY /{fn}/*)  │
└─────────────────────────────────────────────┘
```

### Routing Model

**REST API (v1)**:
```hcl
# Required 4 resources just for routing:
resource "aws_api_gateway_resource" "root" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = each.key
}

resource "aws_api_gateway_method" "root" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.root[each.key].id
  http_method   = "ANY"
  authorization = "NONE"
}

resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.root[each.key].id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "proxy" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.proxy[each.key].id
  http_method   = "ANY"
  authorization = "NONE"
}
```

**HTTP API (v2)**:
```hcl
# Just 2 route resources:
resource "aws_apigatewayv2_route" "root" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "ANY /${each.key}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda[each.key].id}"
}

resource "aws_apigatewayv2_route" "proxy" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "ANY /${each.key}/{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda[each.key].id}"
}
```

### Deployment Model

**REST API (v1)**: Manual deployment required
```hcl
resource "aws_api_gateway_deployment" "fn" {
  depends_on  = [aws_api_gateway_integration.root, aws_api_gateway_integration.proxy]
  rest_api_id = aws_api_gateway_rest_api.api.id
}

resource "aws_api_gateway_stage" "fn" {
  deployment_id = aws_api_gateway_deployment.fn.id
  rest_api_id   = aws_api_gateway_rest_api.api.id
  stage_name    = "dev"
}
```

**HTTP API (v2)**: Auto-deploy
```hcl
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true
}
```

### Endpoint URLs

| API Type | URL Format |
|----------|------------|
| REST API | `https://{api-id}.execute-api.{region}.amazonaws.com/dev/{function}` |
| HTTP API | `https://{api-id}.execute-api.{region}.amazonaws.com/{function}` |

HTTP API uses the `$default` stage, eliminating `/dev` from URLs.

---

## Payload Format v2.0

The migration includes switching from Lambda payload format v1.0 to v2.0.

### Key Differences

| Aspect | v1.0 (REST API) | v2.0 (HTTP API) |
|--------|-----------------|-----------------|
| Headers | Mixed case preserved | **Lowercase normalized** |
| Query strings | `queryStringParameters` | `queryStringParameters` + `rawQueryString` |
| Path parameters | `pathParameters` | `pathParameters` |
| Request context | Verbose | Simplified |
| Cookies | In headers | Dedicated `cookies` array |

### Header Normalization

**Critical change**: HTTP API v2 normalizes all header names to lowercase.

```javascript
// REST API v1 - headers preserve original case
event.headers['Authorization']  // Works
event.headers['authorization']  // May not exist

// HTTP API v2 - headers are always lowercase
event.headers['authorization']  // Always works
event.headers['Authorization']  // Never exists
```

This affects the auth handler implementation:

```javascript
// restHandler.js - simplified due to v2 normalization
const authHeader = event.headers?.authorization;  // Always lowercase
```

### Event Structure Comparison

**REST API v1.0 Event**:
```json
{
  "resource": "/{proxy+}",
  "path": "/listproducts/call",
  "httpMethod": "POST",
  "headers": {
    "Authorization": "Bearer eyJ...",
    "Content-Type": "application/json"
  },
  "queryStringParameters": null,
  "pathParameters": { "proxy": "call" },
  "requestContext": {
    "resourceId": "abc123",
    "resourcePath": "/{proxy+}",
    "httpMethod": "POST",
    "requestId": "uuid",
    "accountId": "123456789",
    "stage": "dev",
    "identity": { ... }
  },
  "body": "{\"key\":\"value\"}"
}
```

**HTTP API v2.0 Event**:
```json
{
  "version": "2.0",
  "routeKey": "ANY /listproducts/{proxy+}",
  "rawPath": "/listproducts/call",
  "rawQueryString": "",
  "headers": {
    "authorization": "Bearer eyJ...",
    "content-type": "application/json"
  },
  "requestContext": {
    "accountId": "123456789",
    "apiId": "abc123",
    "domainName": "abc123.execute-api.us-east-1.amazonaws.com",
    "http": {
      "method": "POST",
      "path": "/listproducts/call",
      "protocol": "HTTP/1.1",
      "sourceIp": "1.2.3.4",
      "userAgent": "..."
    },
    "requestId": "uuid",
    "routeKey": "ANY /listproducts/{proxy+}",
    "stage": "$default",
    "time": "30/Dec/2024:10:00:00 +0000",
    "timeEpoch": 1735556400000
  },
  "pathParameters": { "proxy": "call" },
  "body": "{\"key\":\"value\"}",
  "isBase64Encoded": false
}
```

### BeFaaS Library Compatibility

The `@befaas/lib` rpcHandler automatically handles both payload formats:
- Detects format version from event structure
- Normalizes request/response handling
- No changes needed in function handlers

---

## Infrastructure Changes

### Files Modified

#### 1. `infrastructure/aws/endpoint/main.tf`

**Before**:
```hcl
resource "aws_api_gateway_rest_api" "api" {
  name = "${var.project_name}-api"
}

output "aws_api_gateway_rest_api" {
  value = aws_api_gateway_rest_api.api
}
```

**After**:
```hcl
resource "aws_apigatewayv2_api" "api" {
  name          = "${var.project_name}-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true
}

output "aws_apigatewayv2_api" {
  value = aws_apigatewayv2_api.api
}
```

#### 2. `infrastructure/aws/apigateway.tf`

**Complete replacement** - see diff below:

```diff
-resource "aws_api_gateway_resource" "root" {
-  for_each    = local.fns
-  rest_api_id = data.terraform_remote_state.ep.outputs.aws_api_gateway_rest_api.id
-  parent_id   = data.terraform_remote_state.ep.outputs.aws_api_gateway_rest_api.root_resource_id
-  path_part   = each.key
-}
-
-resource "aws_api_gateway_method" "root" { ... }
-resource "aws_api_gateway_resource" "proxy" { ... }
-resource "aws_api_gateway_method" "proxy" { ... }
-resource "aws_api_gateway_integration" "root" { ... }
-resource "aws_api_gateway_integration" "proxy" { ... }
-resource "aws_api_gateway_deployment" "fn" { ... }
-resource "aws_api_gateway_stage" "fn" { ... }

+resource "aws_apigatewayv2_integration" "lambda" {
+  for_each         = local.fns
+  api_id           = data.terraform_remote_state.ep.outputs.aws_apigatewayv2_api.id
+  integration_type = "AWS_PROXY"
+  integration_uri  = aws_lambda_function.fn[each.key].invoke_arn
+  payload_format_version = "2.0"
+}
+
+resource "aws_apigatewayv2_route" "root" {
+  for_each  = local.fns
+  api_id    = data.terraform_remote_state.ep.outputs.aws_apigatewayv2_api.id
+  route_key = "ANY /${each.key}"
+  target    = "integrations/${aws_apigatewayv2_integration.lambda[each.key].id}"
+}
+
+resource "aws_apigatewayv2_route" "proxy" {
+  for_each  = local.fns
+  api_id    = data.terraform_remote_state.ep.outputs.aws_apigatewayv2_api.id
+  route_key = "ANY /${each.key}/{proxy+}"
+  target    = "integrations/${aws_apigatewayv2_integration.lambda[each.key].id}"
+}
```

**Impact**: 78 lines removed, 24 lines added = **54 lines reduction (69%)**

#### 3. `infrastructure/aws/main.tf`

Lambda permission source ARN update:

```diff
 resource "aws_lambda_permission" "apigw" {
   for_each      = local.fns
   statement_id  = "AllowAPIGatewayInvoke"
   action        = "lambda:InvokeFunction"
   function_name = aws_lambda_function.fn[each.key].function_name
   principal     = "apigateway.amazonaws.com"
-  source_arn    = "${data.terraform_remote_state.ep.outputs.aws_api_gateway_rest_api.execution_arn}/*/*"
+  source_arn    = "${data.terraform_remote_state.ep.outputs.aws_apigatewayv2_api.execution_arn}/*/*"
 }
```

#### 4. `infrastructure/services/publisherAws/gateway.tf`

Same transformation pattern applied to publisher service endpoints.

### Resource Count Comparison

| Resource Type | REST API (per fn) | HTTP API (per fn) |
|---------------|-------------------|-------------------|
| Resource definition | 2 | 0 |
| Method definition | 2 | 0 |
| Integration | 2 | 1 |
| Route | 0 | 2 |
| Deployment | 1 (shared) | 0 |
| Stage | 1 (shared) | 1 (shared) |
| **Total per function** | **8** | **3** |

---

## Code Adaptations

### Auth Header Handling

The header normalization in HTTP API v2 simplified the auth handler:

**Before** (handling both cases):
```javascript
// Had to check multiple cases
const authHeader = event._authHeader
  || event.headers?.authorization
  || event.headers?.Authorization;
```

**After** (v2 guarantees lowercase):
```javascript
// HTTP API v2 normalizes to lowercase
const authHeader = event.headers?.authorization;
```

### Auth Propagation

Function-to-function calls now use HTTP `Authorization` header directly:

**Location**: `experiments/webservice/architectures/faas/authCall.js`

```javascript
async function authCall(fn, contextId, xPair, payload, authHeader = null) {
  const headers = {
    'Content-Type': 'application/json',
    'X-Context': contextId,
    'X-Pair': xPair
  };

  // Pass Authorization header via HTTP (v2 will normalize it)
  if (authHeader) {
    headers['Authorization'] = authHeader;
  }

  const res = await fetch(endpoint, {
    method: 'post',
    body: JSON.stringify(payload),
    headers
  });
  // ...
}
```

### No Changes Required

These components required **no modifications**:
- Function handlers (`handler.js` files)
- Business logic
- Database operations
- `@befaas/lib` usage

---

## Testing and Validation

### Deployment Verification

```bash
# 1. Deploy endpoint infrastructure
cd infrastructure/aws/endpoint
terraform init && terraform apply

# 2. Deploy functions
cd ../
terraform init && terraform apply

# 3. Get endpoint URL
terraform output -raw endpoint_url
```

### Functional Testing

```bash
# Test public endpoint
curl https://{api-id}.execute-api.{region}.amazonaws.com/listproducts/call \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{}'

# Test authenticated endpoint
TOKEN=$(curl -s .../login/call -d '{"username":"test","password":"Test1234"}' | jq -r '.token')

curl https://{api-id}.execute-api.{region}.amazonaws.com/getcart/call \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{}'
```

### Load Testing

```bash
cd artillery
artillery run ../experiments/webservice/workload-minimal-auth-test.yml
```

### Validation Checklist

- [x] All functions respond correctly
- [x] Authentication works (JWT validation)
- [x] Auth propagation in function chains
- [x] Payload format v2.0 parsed correctly
- [x] Headers normalized to lowercase
- [x] No caching behavior observed
- [x] Latency improved (verified in benchmarks)

---

## Rollback Plan

If critical issues are discovered:

```bash
# Revert to REST API configuration
git checkout HEAD~1 infrastructure/aws/endpoint/main.tf
git checkout HEAD~1 infrastructure/aws/apigateway.tf
git checkout HEAD~1 infrastructure/aws/main.tf
git checkout HEAD~1 infrastructure/services/publisherAws/gateway.tf
git checkout HEAD~1 infrastructure/services/publisherAws/main.tf

# Re-deploy
cd infrastructure/aws/endpoint && terraform apply
cd ../aws && terraform apply
```

**Note**: Rollback requires updating any code that relies on v2 header normalization.

---

## References

- [AWS: Choosing between HTTP APIs and REST APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-vs-rest.html)
- [AWS: Working with AWS Lambda proxy integrations for HTTP APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html)
- [AWS: Lambda function payload format version](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html#http-api-develop-integrations-lambda.proxy-format)
- [Original BeFaaS Paper (IEEE IC2E 2021)](https://ieeexplore.ieee.org/document/9383601)