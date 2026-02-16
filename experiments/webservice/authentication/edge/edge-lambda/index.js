/**
 * Lambda@Edge Function for Edge-based Authentication
 *
 * This function runs at CloudFront edge locations and:
 * 1. Validates incoming Cognito JWT tokens
 * 2. Transforms them to short-lived internal tokens
 * 3. Signs internal tokens with Ed25519
 *
 * Constraints:
 * - Max 5s timeout (viewer-request)
 * - Max 1 MB package size
 * - No VPC access
 * - Must be deployed in us-east-1
 */

const crypto = require('crypto');

// These are embedded at build time
const COGNITO_JWKS = process.env.COGNITO_JWKS ? JSON.parse(process.env.COGNITO_JWKS) : null;
const EDGE_PRIVATE_KEY = process.env.EDGE_PRIVATE_KEY;
const COGNITO_ISSUER = process.env.COGNITO_ISSUER;
const COGNITO_CLIENT_ID = process.env.COGNITO_CLIENT_ID;

// Configuration
const INTERNAL_TOKEN_TTL_SECONDS = 45; // Short-lived (paper: 30-60 seconds)
const INTERNAL_ISSUER = 'edge-auth-service';
const INTERNAL_AUDIENCE = 'internal-services';

/**
 * Protected path patterns that require authentication at the edge
 * These paths will return 401 if no valid token is provided
 * Patterns are matched at the end of the URI path (after any prefix like /frontend/)
 */
const PROTECTED_PATH_PATTERNS = [
  '/cart',
  '/addCartItem',
  '/emptyCart',
  '/checkout'
];

/**
 * Check if a path requires authentication
 * @param {string} uri - The request URI
 * @returns {boolean} - True if path requires auth
 */
function requiresAuth(uri) {
  // Normalize URI - extract path without query string
  const path = uri.split('?')[0];

  // Segment-aware matching: split path into segments and check if any
  // segment matches a protected pattern (without leading slash)
  const segments = path.split('/').filter(Boolean);
  return PROTECTED_PATH_PATTERNS.some(pattern => {
    const patternSegment = pattern.replace(/^\//, '');
    return segments.includes(patternSegment);
  });
}

/**
 * Base64URL encode
 */
function base64UrlEncode(buffer) {
  return buffer.toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

/**
 * Base64URL decode
 */
function base64UrlDecode(str) {
  const pad = str.length % 4;
  if (pad) {
    str += '='.repeat(4 - pad);
  }
  str = str.replace(/-/g, '+').replace(/_/g, '/');
  return Buffer.from(str, 'base64');
}

/**
 * Generate 128-bit random request_id (hex-encoded)
 */
function generateRequestId() {
  return crypto.randomBytes(16).toString('hex');
}

/**
 * Hash client IP for origin_hash (SHA-256, truncated to 16 chars)
 */
function hashOrigin(clientIp) {
  const hash = crypto.createHash('sha256').update(clientIp).digest('hex');
  return hash.substring(0, 16);
}

// Cache for JWK kid → KeyObject (Cognito typically has 2 keys)
const jwkKeyCache = new Map();

/**
 * Convert RSA JWK to a Node.js KeyObject for verification.
 * Caches by kid to avoid recreating on every request.
 */
function jwkToPublicKey(jwk) {
  if (jwk.kid && jwkKeyCache.has(jwk.kid)) {
    return jwkKeyCache.get(jwk.kid);
  }
  const keyObject = crypto.createPublicKey({ key: jwk, format: 'jwk' });
  if (jwk.kid) {
    jwkKeyCache.set(jwk.kid, keyObject);
  }
  return keyObject;
}

/**
 * Verify Cognito JWT token
 */
function verifyCognitoToken(token) {
  if (!COGNITO_JWKS || !COGNITO_JWKS.keys) {
    throw new Error('JWKS not configured');
  }

  const parts = token.split('.');
  if (parts.length !== 3) {
    throw new Error('Invalid JWT format');
  }

  const [headerB64, payloadB64, signatureB64] = parts;

  // Parse header to get key ID
  const header = JSON.parse(base64UrlDecode(headerB64).toString());
  const payload = JSON.parse(base64UrlDecode(payloadB64).toString());

  // Check expiration
  const now = Math.floor(Date.now() / 1000);
  if (payload.exp && payload.exp < now - 5) {
    throw new Error('Token expired');
  }

  // Validate token_use claim (must be an access token)
  if (payload.token_use !== 'access') {
    throw new Error('Invalid token_use: expected access token');
  }

  // Validate issuer
  if (COGNITO_ISSUER && payload.iss !== COGNITO_ISSUER) {
    throw new Error('Invalid issuer');
  }

  // Validate client_id (access tokens use 'client_id' claim)
  if (COGNITO_CLIENT_ID && payload.client_id !== COGNITO_CLIENT_ID) {
    throw new Error('Invalid client_id');
  }

  // Find matching key in JWKS
  const key = COGNITO_JWKS.keys.find(k => k.kid === header.kid);
  if (!key) {
    throw new Error(`Key ${header.kid} not found in JWKS`);
  }

  // Verify signature
  const signingInput = `${headerB64}.${payloadB64}`;
  const signature = base64UrlDecode(signatureB64);

  let algorithm;
  switch (header.alg) {
    case 'RS256':
      algorithm = 'RSA-SHA256';
      break;
    case 'RS384':
      algorithm = 'RSA-SHA384';
      break;
    case 'RS512':
      algorithm = 'RSA-SHA512';
      break;
    default:
      throw new Error(`Unsupported algorithm: ${header.alg}`);
  }

  const publicKey = jwkToPublicKey(key);
  const isValid = crypto.verify(
    algorithm,
    Buffer.from(signingInput),
    publicKey,
    signature
  );

  if (!isValid) {
    throw new Error('Invalid signature');
  }

  return payload;
}

// Cache the Ed25519 private key (imported once at module scope)
let cachedPrivateKey = null;

function getPrivateKey() {
  if (cachedPrivateKey) return cachedPrivateKey;
  if (!EDGE_PRIVATE_KEY) {
    throw new Error('EDGE_PRIVATE_KEY not configured');
  }
  const privateKeyDer = Buffer.from(EDGE_PRIVATE_KEY, 'base64');
  cachedPrivateKey = crypto.createPrivateKey({
    key: privateKeyDer,
    format: 'der',
    type: 'pkcs8'
  });
  return cachedPrivateKey;
}

/**
 * Sign internal token with Ed25519
 */
function signInternalToken(payload) {
  const privateKey = getPrivateKey();

  // Create JWT header
  const header = { alg: 'EdDSA', typ: 'JWT' };
  const headerB64 = base64UrlEncode(Buffer.from(JSON.stringify(header)));
  const payloadB64 = base64UrlEncode(Buffer.from(JSON.stringify(payload)));
  const signingInput = `${headerB64}.${payloadB64}`;

  // Sign with Ed25519
  const signature = crypto.sign(null, Buffer.from(signingInput), privateKey);
  const signatureB64 = base64UrlEncode(signature);

  return `${signingInput}.${signatureB64}`;
}

/**
 * Create internal token from external token payload
 */
function createInternalToken(externalPayload, clientIp) {
  const now = Math.floor(Date.now() / 1000);

  const internalPayload = {
    sub: externalPayload.sub || externalPayload.username,
    iss: INTERNAL_ISSUER,
    aud: INTERNAL_AUDIENCE,
    exp: now + INTERNAL_TOKEN_TTL_SECONDS,
    iat: now,
    request_id: generateRequestId(),
    origin_hash: hashOrigin(clientIp || '0.0.0.0')
  };

  return signInternalToken(internalPayload);
}

/**
 * Lambda@Edge handler for viewer-request event
 */
exports.handler = async (event) => {
  const request = event.Records[0].cf.request;
  const headers = request.headers;
  const uri = request.uri;

  // Extract Authorization header
  const authHeaderArray = headers.authorization || headers.Authorization;
  const authHeader = authHeaderArray?.[0]?.value;

  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    // No auth header - check if this is a protected endpoint
    if (requiresAuth(uri)) {
      // Protected endpoint without auth - return 401 immediately
      console.error(`Edge auth: Protected endpoint ${uri} accessed without token`);
      return {
        status: '401',
        statusDescription: 'Unauthorized',
        body: JSON.stringify({
          error: 'Authentication required',
          message: `Endpoint ${uri} requires authentication`,
          path: uri
        }),
        headers: {
          'content-type': [{ key: 'Content-Type', value: 'application/json' }],
          'x-befaas-edge-error': [{ key: 'X-BeFaaS-Edge-Error', value: 'Missing authentication token' }]
        }
      };
    }

    // Public endpoint - pass through without auth
    // Add marker that request was processed by edge (for logging)
    // Note: X-Edge-* headers are reserved by CloudFront, use X-BeFaaS-* instead
    request.headers['x-befaas-edge-processed'] = [{
      key: 'X-BeFaaS-Edge-Processed',
      value: 'passthrough'
    }];
    return request;
  }

  const externalToken = authHeader.replace('Bearer ', '');

  try {
    // 1. Verify external token (Cognito JWT)
    const externalPayload = verifyCognitoToken(externalToken);

    // 2. Extract client IP for origin_hash
    const clientIp = request.clientIp || '0.0.0.0';

    // 3. Create and sign internal token
    const internalToken = createInternalToken(externalPayload, clientIp);

    // 4. Replace Authorization header with internal token
    request.headers.authorization = [{
      key: 'Authorization',
      value: `Bearer ${internalToken}`
    }];

    // 5. Add edge processing marker
    // Note: X-Edge-* headers are reserved by CloudFront, use X-BeFaaS-* instead
    request.headers['x-befaas-edge-processed'] = [{
      key: 'X-BeFaaS-Edge-Processed',
      value: 'true'
    }];

    // 6. Add original subject for logging (truncated)
    const sub = externalPayload.sub || externalPayload.username || 'unknown';
    request.headers['x-befaas-edge-subject'] = [{
      key: 'X-BeFaaS-Edge-Subject',
      value: sub.substring(0, 36)
    }];

    return request;

  } catch (error) {
    // Token validation failed - return 401
    // Log full error for debugging but don't expose details to clients
    console.error('Edge auth error:', error.message);

    return {
      status: '401',
      statusDescription: 'Unauthorized',
      body: JSON.stringify({
        error: 'Invalid or expired token'
      }),
      headers: {
        'content-type': [{ key: 'Content-Type', value: 'application/json' }]
      }
    };
  }
};