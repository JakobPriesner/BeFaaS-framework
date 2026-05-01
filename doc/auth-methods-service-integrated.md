# Service-Integrated Authentication Methods Documentation

This document provides comprehensive documentation for the `service-integrated` and `service-integrated-manual` authentication methods used in the BeFaaS framework for benchmarking serverless architectures.

## Table of Contents

1. [Overview](#overview)
2. [service-integrated (AWS Cognito)](#service-integrated-aws-cognito)
3. [service-integrated-manual (Manual JWT)](#service-integrated-manual-manual-jwt)
4. [Comparison](#comparison)
5. [Infrastructure Requirements](#infrastructure-requirements)
6. [API Reference](#api-reference)
7. [Protected vs Public Functions](#protected-vs-public-functions)

---

## Overview

Both authentication methods implement JWT-based authentication with the same API interface but differ in their implementation approach:

| Aspect | `service-integrated` | `service-integrated-manual` |
|--------|----------------------|----------------------------|
| Token Verification | AWS Cognito (remote) | Local JWT library |
| User Storage | AWS Cognito User Pool | Redis |
| Password Management | AWS-managed | bcrypt hashing |
| Key Type | Asymmetric (RSA) | Symmetric (HS256) |
| Network Dependency | Yes (AWS API calls) | No (local only) |

---

## service-integrated (AWS Cognito)

This method uses AWS Cognito as a managed authentication service. JWT tokens are issued and verified against AWS Cognito User Pools.

### Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Client    │────▶│  Your Service    │────▶│  AWS Cognito    │
│             │◀────│  (Lambda/ECS)    │◀────│  User Pool      │
└─────────────┘     └──────────────────┘     └─────────────────┘
```

### Dependencies

```json
{
  "dependencies": {
    "aws-jwt-verify": "^4.0.1"
  }
}
```

For login/register operations, the AWS SDK is also required (typically available in Lambda):
- `@aws-sdk/client-cognito-identity-provider`
- `@smithy/node-http-handler`

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COGNITO_USER_POOL_ID` | Yes | - | AWS Cognito User Pool ID |
| `COGNITO_CLIENT_ID` | Yes | - | Cognito User Pool Client ID |
| `COGNITO_CLIENT_SECRET` | No | - | Client secret (if configured) |
| `AWS_REGION` | No | `us-east-1` | AWS region |

### Source Code

#### Token Verification (`index.js`)

```javascript
const { CognitoJwtVerifier } = require('aws-jwt-verify');
const { performance } = require('perf_hooks');

const userPoolId = process.env.COGNITO_USER_POOL_ID;
const clientId = process.env.COGNITO_CLIENT_ID;
const fnName = process.env.BEFAAS_FN_NAME || 'unknownFn';
const deploymentId = process.env.BEFAAS_DEPLOYMENT_ID || 'unknownDeploymentId';

// Log auth timing in BEFAAS format
function logAuthTiming(contextId, durationMs, success) {
  console.log(
    'BEFAAS' +
      JSON.stringify({
        timestamp: new Date().getTime(),
        now: performance.now(),
        deploymentId,
        fn: { name: fnName },
        event: {
          contextId,
          authCheck: {
            durationMs,
            success
          }
        }
      })
  );
}

async function verifyJWT(event, contextId) {
  const startTime = performance.now();
  const logContextId = contextId || 'unknown';

  try {
    const authHeader = event.headers?.authorization || event.headers?.Authorization;

    if (!authHeader) {
      const duration = performance.now() - startTime;
      logAuthTiming(logContextId, duration, false);
      return false;
    }

    const token = authHeader.replace(/^Bearer\s+/i, '');

    const verifier = CognitoJwtVerifier.create({
      userPoolId,
      tokenUse: 'access',
      clientId,
    });

    const payload = await verifier.verify(token);

    const duration = performance.now() - startTime;
    logAuthTiming(logContextId, duration, true);

    return payload;
  } catch (err) {
    const duration = performance.now() - startTime;
    logAuthTiming(logContextId, duration, false);
    const errorMsg = err.message || String(err);
    // Throw timeout errors so they can be handled with 424 status
    if (errorMsg.includes('time-out') || errorMsg.includes('timeout') || errorMsg.includes('ETIMEDOUT')) {
      console.error('JWT verification timeout:', err);
      const timeoutError = new Error('AUTH_TIMEOUT');
      timeoutError.isAuthTimeout = true;
      throw timeoutError;
    }
    console.error('Error verifying JWT:', err);
    return false;
  }
}

module.exports = { verifyJWT };
```

#### Login (`login.js`)

```javascript
const { CognitoIdentityProviderClient, InitiateAuthCommand } = require('@aws-sdk/client-cognito-identity-provider')
const { NodeHttpHandler } = require('@smithy/node-http-handler')

const cognitoClient = new CognitoIdentityProviderClient({
  region: process.env.AWS_REGION || 'us-east-1',
  requestHandler: new NodeHttpHandler({
    maxSockets: 200,
    connectionTimeout: 10000,
    socketTimeout: 10000
  })
})

const COGNITO_CLIENT_ID = process.env.COGNITO_CLIENT_ID

/**
 * Login Service for 'service-integrated' auth mode.
 * Authenticates a user against Cognito and returns JWT tokens.
 *
 * Request Body: {
 *   "userName": "testuser",
 *   "password": "TestPassword123!"
 * }
 *
 * Response on success: {
 *   "success": true,
 *   "accessToken": "...",
 *   "idToken": "...",
 *   "refreshToken": "..."
 * }
 *
 * Response on failure: {
 *   "success": false,
 *   "error": "..."
 * }
 */
async function handle(event, ctx) {
  const { userName, password } = event

  if (!userName || !password) {
    return { success: false, error: 'userName and password are required' }
  }

  try {
    const authParameters = {
      USERNAME: userName,
      PASSWORD: password
    }

    const command = new InitiateAuthCommand({
      AuthFlow: 'USER_PASSWORD_AUTH',
      ClientId: COGNITO_CLIENT_ID,
      AuthParameters: authParameters
    })

    const response = await cognitoClient.send(command)

    return {
      success: true,
      accessToken: response.AuthenticationResult.AccessToken,
      idToken: response.AuthenticationResult.IdToken,
      refreshToken: response.AuthenticationResult.RefreshToken
    }
  } catch (error) {
    console.error('Login error:', error.message)
    return { success: false, error: error.message }
  }
}

module.exports = handle
```

#### Registration (`register.js`)

```javascript
const { CognitoIdentityProviderClient, SignUpCommand, AdminConfirmSignUpCommand } = require('@aws-sdk/client-cognito-identity-provider')
const { NodeHttpHandler } = require('@smithy/node-http-handler')

const cognitoClient = new CognitoIdentityProviderClient({
  region: process.env.AWS_REGION || 'us-east-1',
  requestHandler: new NodeHttpHandler({
    maxSockets: 200,
    connectionTimeout: 10000,
    socketTimeout: 10000
  })
})

const COGNITO_CLIENT_ID = process.env.COGNITO_CLIENT_ID
const COGNITO_CLIENT_SECRET = process.env.COGNITO_CLIENT_SECRET
const COGNITO_USER_POOL_ID = process.env.COGNITO_USER_POOL_ID

/**
 * Register Service for 'service-integrated' auth mode.
 * Creates a new user in Cognito.
 *
 * Request Body: {
 *   "userName": "testuser",
 *   "password": "TestPassword123!"
 * }
 *
 * Response on success: {
 *   "success": true,
 *   "message": "User registered successfully"
 * }
 *
 * Response on failure: {
 *   "success": false,
 *   "error": "..."
 * }
 */
async function handle(event, ctx) {
  const { userName, password } = event

  if (!userName || !password) {
    return { success: false, error: 'userName and password are required' }
  }

  try {
    const signUpParams = {
      ClientId: COGNITO_CLIENT_ID,
      Username: userName,
      Password: password
    }

    // Only include SecretHash if client secret is configured
    if (COGNITO_CLIENT_SECRET) {
      const crypto = require('crypto')
      const secretHash = crypto
        .createHmac('SHA256', COGNITO_CLIENT_SECRET)
        .update(userName + COGNITO_CLIENT_ID)
        .digest('base64')
      signUpParams.SecretHash = secretHash
    }

    const signUpCommand = new SignUpCommand(signUpParams)

    await cognitoClient.send(signUpCommand)

    // Auto-confirm the user for demo purposes
    const confirmCommand = new AdminConfirmSignUpCommand({
      UserPoolId: COGNITO_USER_POOL_ID,
      Username: userName
    })

    await cognitoClient.send(confirmCommand)

    return {
      success: true,
      message: 'User registered successfully'
    }
  } catch (error) {
    console.error('Registration error:', error.message)

    if (error.name === 'UsernameExistsException') {
      return { success: false, error: 'Username already exists' }
    }

    return { success: false, error: error.message }
  }
}

module.exports = handle
```

### How It Works

1. **Registration**: Creates a user in AWS Cognito User Pool using `SignUpCommand`, then auto-confirms with `AdminConfirmSignUpCommand`
2. **Login**: Authenticates via `InitiateAuthCommand` with `USER_PASSWORD_AUTH` flow, returns Cognito-issued JWTs
3. **Verification**: Uses `aws-jwt-verify` library which fetches Cognito's public keys (JWKS) and validates token signature, expiry, and claims

### Token Characteristics

- **Access Token**: 60 minutes validity, used for API authorization
- **ID Token**: 60 minutes validity, contains user identity claims
- **Refresh Token**: 30 days validity, used to obtain new access/ID tokens
- **Algorithm**: RS256 (asymmetric - Cognito holds private key)

---

## service-integrated-manual (Manual JWT)

This method implements JWT authentication manually using the `jsonwebtoken` library with symmetric key signing. User data is stored in Redis.

### Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Client    │────▶│  Your Service    │────▶│     Redis       │
│             │◀────│  (Lambda/ECS)    │◀────│  (User Data)    │
└─────────────┘     └──────────────────┘     └─────────────────┘
                            │
                    (Local JWT verification -
                     no external calls)
```

### Dependencies

```json
{
  "dependencies": {
    "jsonwebtoken": "^9.0.2",
    "bcryptjs": "^2.4.3"
  }
}
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JWT_SECRET` | No | `befaas-default-secret-change-in-production` | Shared secret for HS256 |
| `JWT_EXPIRES_IN` | No | `1h` | Access/ID token expiry |
| `BCRYPT_ROUNDS` | No | `10` | bcrypt hash cost factor |

### Source Code

#### Token Verification (`index.js`)

```javascript
const jwt = require('jsonwebtoken')
const { performance } = require('perf_hooks')

const JWT_SECRET = process.env.JWT_SECRET || 'befaas-default-secret-change-in-production'
const fnName = process.env.BEFAAS_FN_NAME || 'unknownFn'
const deploymentId = process.env.BEFAAS_DEPLOYMENT_ID || 'unknownDeploymentId'

// Log auth timing in BEFAAS format
function logAuthTiming(contextId, xPair, durationMs, success) {
  console.log(
    'BEFAAS' +
      JSON.stringify({
        timestamp: new Date().getTime(),
        now: performance.now(),
        deploymentId,
        fn: { name: fnName },
        event: {
          contextId,
          xPair,
          authCheck: {
            durationMs,
            success
          }
        }
      })
  )
}

/**
 * Verifies a JWT token from the Authorization header.
 * Uses manual JWT verification with jsonwebtoken library.
 *
 * @param {Object} event - The event object containing headers
 * @param {string} contextId - The context ID for logging (session ID)
 * @param {string} xPair - The xPair ID for request/response correlation
 * @returns {Object|false} - Returns the decoded payload if valid, false otherwise
 */
async function verifyJWT(event, contextId, xPair) {
  const startTime = performance.now()
  const logContextId = contextId || 'unknown'
  const logXPair = xPair || 'unknown'

  try {
    const authHeader = event.headers?.authorization || event.headers?.Authorization

    if (!authHeader) {
      const duration = performance.now() - startTime
      logAuthTiming(logContextId, logXPair, duration, false)
      return false
    }

    const token = authHeader.replace(/^Bearer\s+/i, '')

    // Verify the JWT token
    const payload = jwt.verify(token, JWT_SECRET, {
      algorithms: ['HS256']
    })

    const duration = performance.now() - startTime
    logAuthTiming(logContextId, logXPair, duration, true)

    return payload
  } catch (err) {
    const duration = performance.now() - startTime
    logAuthTiming(logContextId, logXPair, duration, false)
    console.error('Error verifying JWT:', err.message)
    return false
  }
}

module.exports = { verifyJWT }
```

#### Login (`login.js`)

```javascript
const jwt = require('jsonwebtoken')
const bcrypt = require('bcryptjs')

const JWT_SECRET = process.env.JWT_SECRET || 'befaas-default-secret-change-in-production'
const JWT_EXPIRES_IN = process.env.JWT_EXPIRES_IN || '1h'

/**
 * Login Service for 'service-integrated-manual' auth mode.
 * Validates user against Redis and generates real JWT tokens.
 *
 * Request Body: {
 *   "userName": "testuser",
 *   "password": "TestPassword123!"
 * }
 *
 * Response on success: {
 *   "success": true,
 *   "accessToken": "<jwt-access-token>",
 *   "idToken": "<jwt-id-token>",
 *   "refreshToken": "<jwt-refresh-token>"
 * }
 *
 * Response on failure: {
 *   "success": false,
 *   "error": "..."
 * }
 */
async function handle(event, ctx) {
  const { userName, password } = event

  if (!userName || !password) {
    return { success: false, error: 'userName and password are required' }
  }

  const userKey = `user:${userName}`

  // Check if user exists in Redis
  const user = await ctx.db.get(userKey)
  if (!user) {
    return { success: false, error: 'User not found' }
  }

  // Verify password using bcrypt
  const isValidPassword = await bcrypt.compare(password, user.passwordHash)
  if (!isValidPassword) {
    return { success: false, error: 'Invalid password' }
  }

  // Generate JWT tokens
  const tokenPayload = {
    sub: userName,
    username: userName,
    iat: Math.floor(Date.now() / 1000)
  }

  const accessToken = jwt.sign(
    { ...tokenPayload, token_use: 'access' },
    JWT_SECRET,
    { algorithm: 'HS256', expiresIn: JWT_EXPIRES_IN }
  )

  const idToken = jwt.sign(
    { ...tokenPayload, token_use: 'id' },
    JWT_SECRET,
    { algorithm: 'HS256', expiresIn: JWT_EXPIRES_IN }
  )

  // Refresh token has longer expiry
  const refreshToken = jwt.sign(
    { ...tokenPayload, token_use: 'refresh' },
    JWT_SECRET,
    { algorithm: 'HS256', expiresIn: '7d' }
  )

  return {
    success: true,
    accessToken,
    idToken,
    refreshToken
  }
}

module.exports = handle
```

#### Registration (`register.js`)

```javascript
const bcrypt = require('bcryptjs')

const BCRYPT_ROUNDS = parseInt(process.env.BCRYPT_ROUNDS, 10) || 10

/**
 * Register Service for 'service-integrated-manual' auth mode.
 * Stores user in Redis with bcrypt-hashed password.
 *
 * Request Body: {
 *   "userName": "testuser",
 *   "password": "TestPassword123!"
 * }
 *
 * Response on success: {
 *   "success": true,
 *   "message": "User registered successfully"
 * }
 *
 * Response on failure: {
 *   "success": false,
 *   "error": "..."
 * }
 */
async function handle(event, ctx) {
  const { userName, password } = event

  if (!userName || !password) {
    return { success: false, error: 'userName and password are required' }
  }

  const userKey = `user:${userName}`

  // Check if user already exists
  const existingUser = await ctx.db.get(userKey)
  if (existingUser) {
    return { success: false, error: 'Username already exists' }
  }

  // Hash the password with bcrypt
  const passwordHash = await bcrypt.hash(password, BCRYPT_ROUNDS)

  // Store user in Redis with hashed password
  await ctx.db.set(userKey, {
    userName,
    passwordHash,
    createdAt: new Date().toISOString()
  })

  return {
    success: true,
    message: 'User registered successfully'
  }
}

module.exports = handle
```

### How It Works

1. **Registration**: Hashes password with bcrypt and stores user object in Redis under key `user:<userName>`
2. **Login**: Retrieves user from Redis, verifies password with bcrypt, generates three JWT tokens signed with shared secret
3. **Verification**: Uses `jsonwebtoken.verify()` with HS256 algorithm - purely local operation with no network calls

### Token Characteristics

- **Access Token**: 1 hour validity (configurable via `JWT_EXPIRES_IN`)
- **ID Token**: 1 hour validity (same as access token)
- **Refresh Token**: 7 days validity (hardcoded)
- **Algorithm**: HS256 (symmetric - same secret for signing and verification)

### Redis Data Structure

```json
// Key: user:testuser
{
  "userName": "testuser",
  "passwordHash": "$2a$10$...",
  "createdAt": "2024-01-15T10:30:00.000Z"
}
```

---

## Comparison

### Performance Characteristics

| Metric | `service-integrated` | `service-integrated-manual` |
|--------|----------------------|----------------------------|
| Verification Latency | 50-200ms (network call) | 1-5ms (local) |
| Login Latency | 100-500ms (Cognito API) | 10-50ms (Redis + bcrypt) |
| Registration Latency | 200-800ms (2 Cognito calls) | 50-200ms (bcrypt + Redis) |
| Network I/O | Required (AWS API) | None for verification |

### Security Considerations

| Aspect | `service-integrated` | `service-integrated-manual` |
|--------|----------------------|----------------------------|
| Key Management | AWS-managed (automatic rotation) | Manual (must secure JWT_SECRET) |
| Token Revocation | Supported via Cognito | Not built-in (requires custom logic) |
| Password Storage | AWS-managed (secure) | bcrypt in Redis (you manage) |
| Compliance | AWS compliance certifications | Your responsibility |

### Cost Implications

| Component | `service-integrated` | `service-integrated-manual` |
|-----------|----------------------|----------------------------|
| User Pool | AWS Cognito pricing (first 50K MAU free) | None |
| Token Verification | Included in Cognito | None |
| Data Storage | Cognito-managed | Redis costs |

---

## Infrastructure Requirements

### service-integrated (AWS Cognito)

Requires AWS Cognito User Pool. The infrastructure can be deployed in two modes:

#### Option 1: Persistent Pool (Recommended)

A single Cognito pool shared across experiments, preserving users.

**Terraform (`infrastructure/services/cognito/main.tf`):**

```hcl
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  description = "AWS region"
  default     = "us-east-1"
}

variable "pool_name" {
  description = "Name for the Cognito User Pool"
  default     = "befaas-persistent-pool"
}

# Cognito User Pool
resource "aws_cognito_user_pool" "main" {
  name = var.pool_name

  password_policy {
    minimum_length                   = 8
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  tags = {
    Name    = var.pool_name
    Purpose = "BeFaaS persistent user pool"
  }
}

# Cognito User Pool Client
resource "aws_cognito_user_pool_client" "main" {
  name         = "${var.pool_name}-client"
  user_pool_id = aws_cognito_user_pool.main.id

  access_token_validity  = 60 # minutes
  id_token_validity      = 60 # minutes
  refresh_token_validity = 30 # days

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH"
  ]

  generate_secret = false

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code", "implicit"]
  allowed_oauth_scopes                 = ["email", "openid", "profile"]

  callback_urls = ["http://localhost:3000/callback"]
  logout_urls   = ["http://localhost:3000/logout"]

  enable_token_revocation       = true
  prevent_user_existence_errors = "ENABLED"
}

# Cognito User Pool Domain
resource "aws_cognito_user_pool_domain" "main" {
  domain       = var.pool_name
  user_pool_id = aws_cognito_user_pool.main.id
}

# Outputs
output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.main.id
}

output "cognito_user_pool_endpoint" {
  value = aws_cognito_user_pool.main.endpoint
}
```

**Deployment:**

```bash
cd infrastructure/services/cognito
terraform init
terraform apply
```

#### Option 2: Per-Experiment Pool

Creates a new Cognito pool for each experiment run. Set `use_persistent_cognito = false` in the experiment's Terraform variables.

### service-integrated-manual (Redis)

Requires a Redis instance accessible from your services. No AWS Cognito infrastructure needed.

---

## API Reference

Both methods share the same API interface:

### Register

**Endpoint:** `POST /register`

**Request:**
```json
{
  "userName": "testuser",
  "password": "TestPassword123!"
}
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "User registered successfully"
}
```

**Error Response (200):**
```json
{
  "success": false,
  "error": "Username already exists"
}
```

### Login

**Endpoint:** `POST /login`

**Request:**
```json
{
  "userName": "testuser",
  "password": "TestPassword123!"
}
```

**Success Response (200):**
```json
{
  "success": true,
  "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "idToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refreshToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Error Response (200):**
```json
{
  "success": false,
  "error": "Invalid password"
}
```

### Protected Endpoints

Include the access token in the `Authorization` header:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## Protected vs Public Functions

The framework distinguishes between functions that require authentication and public functions:

### Functions Requiring Authentication

These endpoints verify the JWT before processing:

- `getcart` - Get user's shopping cart
- `addcartitem` - Add item to cart
- `emptycart` - Clear the cart
- `cartkvstorage` - Cart key-value storage operations
- `checkout` - Process checkout
- `payment` - Process payment

### Public Functions (No Authentication)

These endpoints skip authentication entirely for better performance:

- `listproducts` - List all products
- `getproduct` - Get product details
- `searchproducts` - Search products
- `listrecommendations` - Get recommendations
- `getads` - Get advertisements
- `supportedcurrencies` - List currencies
- `currency` - Currency conversion
- `shipmentquote` - Get shipping quote
- `shiporder` - Ship an order
- `email` - Send email
- `frontend` - Frontend service
- `login` - User login
- `register` - User registration

### Checking Auth Requirements (Code)

```javascript
const { requiresAuth, isPublic } = require('./authConfig')

// Check if function needs auth
if (requiresAuth('getcart')) {
  // Verify JWT before processing
}

// Check if function is public
if (isPublic('listproducts')) {
  // Skip auth, process directly
}
```

---

## Logging Format

Both methods log authentication timing in the BEFAAS format for benchmarking:

```json
{
  "timestamp": 1705312200000,
  "now": 123.456,
  "deploymentId": "experiment-123",
  "fn": { "name": "getcart" },
  "event": {
    "contextId": "session-abc-123",
    "xPair": "req-xyz-789",
    "authCheck": {
      "durationMs": 2.345,
      "success": true
    }
  }
}
```

This allows measuring authentication overhead across different methods and architectures.