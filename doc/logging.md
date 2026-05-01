# BeFaaS Logging System

This document describes the comprehensive logging system used in the BeFaaS framework for performance measurement and request tracing.

## Overview

The BeFaaS logging system consists of two complementary components:

1. **Artillery Client-Side Logging** - Measures end-to-end request timing from the client perspective
2. **Service-Internal Logging** - Measures specific internal operations like authentication token verification

Both logging systems use structured JSON output with the prefix `BEFAAS` to enable easy parsing and correlation.

---

## 1. Artillery Client-Side Logging

### Location
`artillery/logger.js`

### Purpose
Tracks all HTTP requests from Artillery load tests, measuring end-to-end latency including network overhead, API Gateway processing, Lambda cold starts, and service execution time.

### How It Works

The Artillery logger uses hooks to instrument requests:

```javascript
// Before each request
beforeRequest: function(requestParams, context, ee, next) {
  const contextId = uuidv4();  // Unique session/user ID
  const pairId = uuidv4();     // Unique request/response pair ID

  // Store IDs for response correlation
  context.vars.contextId = contextId;
  context.vars.pairId = pairId;

  // Log request start
  logEvent('beforeRequest', {
    url: requestParams.url,
    contextId,
    pairId,
    timestamp: Date.now(),
    performanceTime: performance.now()
  });
}

// After response received
afterResponse: function(requestParams, response, context, ee, next) {
  // Log response end with same IDs for correlation
  logEvent('afterResponse', {
    url: requestParams.url,
    contextId: context.vars.contextId,
    pairId: context.vars.pairId,
    timestamp: Date.now(),
    performanceTime: performance.now(),
    statusCode: response.statusCode
  });
}
```

### Log Format

```json
BEFAAS{
  "libraryVersion": "1.0.0",
  "deploymentId": "exp-123",
  "timestamp": 1703251200000,
  "performanceTime": 12345.678,
  "functionName": "artillery-logger",
  "event": {
    "url": "https://api.example.com/login",
    "contextId": "a1b2c3d4-...",
    "pairId": "e5f6g7h8-...",
    "type": "beforeRequest"
  }
}
```

### Key Fields

- **`contextId`**: Unique identifier for a user session (persists across multiple requests from the same virtual user)
- **`pairId`**: Unique identifier for a single request/response pair
- **`timestamp`**: Unix timestamp in milliseconds
- **`performanceTime`**: High-resolution time from `performance.now()`
- **`url`**: The request URL

### What It Measures

✅ **Included in measurement:**
- Network latency (client ↔ server)
- API Gateway overhead
- Lambda cold starts
- Service initialization
- Authentication verification
- Business logic execution
- Response serialization

❌ **Not measured separately:**
- Individual internal operations (use service-internal logging for this)

---

## 2. Service-Internal Authentication Logging

### Location
- `experiments/webservice/authentication/service-integrated/index.js` (Cognito)
- `experiments/webservice/authentication/service-integrated-manual/index.js` (Manual JWT)

### Purpose
Measures the **exact duration** of JWT token verification, isolated from all other processing.

### How It Works

```javascript
async function verifyJWT(event, contextId, xPair) {
  const startTime = performance.now();

  try {
    // Extract token from Authorization header
    const authHeader = event.headers?.authorization || event.headers?.Authorization;

    if (!authHeader) {
      const duration = performance.now() - startTime;
      logAuthTiming(contextId, xPair, duration, false);
      return false;
    }

    const token = authHeader.replace(/^Bearer\s+/i, '');

    // Perform token verification (Cognito or manual JWT)
    const payload = await verifier.verify(token);

    // Log exact verification duration
    const duration = performance.now() - startTime;
    logAuthTiming(contextId, xPair, duration, true);

    return payload;
  } catch (err) {
    const duration = performance.now() - startTime;
    logAuthTiming(contextId, xPair, duration, false);
    console.error('Error verifying JWT:', err);
    return false;
  }
}
```

### Log Format

```json
BEFAAS{
  "timestamp": 1703251200000,
  "now": 12345.678,
  "deploymentId": "exp-123",
  "fn": {
    "name": "frontend"
  },
  "event": {
    "contextId": "a1b2c3d4-...",
    "xPair": "e5f6g7h8-...",
    "authCheck": {
      "durationMs": 45.3,
      "success": true
    }
  }
}
```

### Key Fields

- **`contextId`**: Same as Artillery's contextId - enables correlation!
- **`xPair`**: Request/response pair ID for correlation
- **`fn.name`**: The function/service performing authentication
- **`authCheck.durationMs`**: Exact token verification duration in milliseconds
- **`authCheck.success`**: Whether verification succeeded

### What It Measures

✅ **Included in measurement:**
- JWT token parsing
- Signature verification
- Claims validation
- Cognito API calls (if using Cognito verifier)

❌ **Not included:**
- Network latency
- API Gateway processing
- Lambda initialization
- Business logic after authentication

---

## Correlating Artillery and Service Logs

The `contextId` field enables correlation between Artillery client logs and service-internal logs:

### Example Analysis Flow

1. **Artillery logs request:**
```json
BEFAAS{"event": {"type": "beforeRequest", "contextId": "abc-123", "pairId": "req-1", "url": "/api/products"}, "performanceTime": 1000.0}
```

2. **Service verifies authentication:**
```json
BEFAAS{"event": {"contextId": "abc-123", "xPair": "req-1", "authCheck": {"durationMs": 45.3, "success": true}}, "fn": {"name": "getproduct"}}
```

3. **Artillery logs response:**
```json
BEFAAS{"event": {"type": "afterResponse", "contextId": "abc-123", "pairId": "req-1", "statusCode": 200}, "performanceTime": 1150.5}
```

### Calculating Overhead

```
Total Request Time = 1150.5 - 1000.0 = 150.5 ms
Authentication Time = 45.3 ms
Other Overhead = 150.5 - 45.3 = 105.2 ms
  (Network + API Gateway + Lambda Init + Business Logic)
```

---

## Analysis Use Cases

### 1. Authentication Performance Under Load

By correlating logs, you can analyze:
- How authentication duration changes with increasing load
- Whether token verification becomes a bottleneck
- Cold start impact vs warm execution
- Authentication failure rates under stress

### Example Query:
```bash
# Extract all auth timings with their timestamps
grep "authCheck" logs.txt | jq '{timestamp, fn: .fn.name, authMs: .event.authCheck.durationMs, success: .event.authCheck.success}'
```

### 2. Request Breakdown

Compare Artillery end-to-end time with internal auth time:

```python
# Pseudocode
for each contextId:
    artillery_duration = afterResponse.time - beforeRequest.time
    auth_duration = authCheck.durationMs
    other_duration = artillery_duration - auth_duration

    print(f"Request {contextId}:")
    print(f"  Total: {artillery_duration}ms")
    print(f"  Auth: {auth_duration}ms ({auth_duration/artillery_duration*100}%)")
    print(f"  Other: {other_duration}ms ({other_duration/artillery_duration*100}%)")
```

### 3. Load Pattern Analysis

Correlate authentication duration with load characteristics:

```python
# Group by time windows
for time_window in experiment:
    auth_times = get_auth_durations(time_window)
    request_rate = get_request_rate(time_window)

    print(f"At {request_rate} req/s:")
    print(f"  Auth p50: {percentile(auth_times, 50)}ms")
    print(f"  Auth p95: {percentile(auth_times, 95)}ms")
    print(f"  Auth p99: {percentile(auth_times, 99)}ms")
```

---

## Log Collection

Logs are written to stdout with the `BEFAAS` prefix, making them easy to filter:

```bash
# Extract all BeFaaS logs
grep "^BEFAAS" lambda-logs.txt > befaas-logs.jsonl

# Parse as JSON (one per line)
cat befaas-logs.jsonl | sed 's/^BEFAAS//' | jq '.'
```

For AWS Lambda, logs are collected from CloudWatch Logs. See `scripts/experiment/cloudwatch-metrics.js` for automated log retrieval.

---

## Environment Variables

### Artillery Logger
- `BEFAAS_DEPLOYMENT_ID`: Unique identifier for the experiment run

### Service Authentication
- `BEFAAS_FN_NAME`: Function/service name for identification
- `BEFAAS_DEPLOYMENT_ID`: Same deployment ID as Artillery
- `COGNITO_USER_POOL_ID`: AWS Cognito User Pool (for Cognito auth)
- `COGNITO_CLIENT_ID`: AWS Cognito Client ID (for Cognito auth)
- `JWT_SECRET`: Secret key for manual JWT verification

---

## Extending the Logging System

To add logging for other internal operations:

```javascript
const { performance } = require('perf_hooks');

function logOperation(contextId, xPair, operationType, durationMs, metadata) {
  process.stdout.write(
    'BEFAAS' +
      JSON.stringify({
        timestamp: new Date().getTime(),
        now: performance.now(),
        deploymentId: process.env.BEFAAS_DEPLOYMENT_ID,
        fn: { name: process.env.BEFAAS_FN_NAME },
        event: {
          contextId,
          xPair,
          [operationType]: {
            durationMs,
            ...metadata
          }
        }
      }) +
      '\n'
  );
}

// Usage
const start = performance.now();
// ... perform operation ...
const duration = performance.now() - start;
logOperation(contextId, xPair, 'databaseQuery', duration, { query: 'SELECT ...', rows: 42 });
```

---

## Best Practices

1. **Always propagate contextId and xPair** through your call chain to enable correlation
2. **Use `performance.now()`** for high-resolution timing (microsecond precision)
3. **Log both success and failure cases** to analyze error impact
4. **Include operation metadata** to enable detailed analysis
5. **Write to stdout** with the `BEFAAS` prefix for consistent parsing
6. **Measure only the operation** you care about, not surrounding code

---

## Summary

| Logging Component | Purpose | Granularity | Use Cases |
|-------------------|---------|-------------|-----------|
| **Artillery Logger** | End-to-end request timing | Request-level | Load testing, overall latency, user experience |
| **Auth Timing** | Token verification duration | Operation-level | Auth performance, bottleneck analysis, optimization |
| **Correlation (contextId)** | Link client and service logs | Session/request | Request breakdown, overhead calculation, debugging |

The combination of client-side and service-internal logging provides complete visibility into both user-perceived performance and internal operation efficiency.
