const { jwtVerify, importSPKI } = require('jose')
const { performance } = require('perf_hooks')

const fnName = process.env.BEFAAS_FN_NAME || 'unknownFn'
const deploymentId = process.env.BEFAAS_DEPLOYMENT_ID || 'unknownDeploymentId'

// Cache the imported public key to avoid re-parsing on every request
let cachedPublicKey = null

async function getPublicKey() {
  if (cachedPublicKey) return cachedPublicKey
  const pem = Buffer.from(process.env.JWT_PUBLIC_KEY, 'base64').toString('utf8')
  cachedPublicKey = await importSPKI(pem, 'EdDSA')
  return cachedPublicKey
}

// Log auth timing in BEFAAS format
// Using console.log instead of process.stdout.write because Lambda CloudWatch
// captures console.log reliably but may not capture raw stdout writes
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
 * Uses EdDSA (Ed25519) verification with the jose library.
 *
 * @param {Object} event - The event object containing headers
 * @param {string} contextId - The context ID for logging (session ID)
 * @param {string} xPair - The xPair ID for request/response correlation
 * @returns {Object|false} - Returns the decoded payload if valid, false otherwise
 */
async function verifyJWT(event, contextId, xPair) {
  const startTime = performance.now()
  // Use 'unknown' as fallback to ensure auth timing is always logged
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

    // Verify the JWT token using EdDSA
    const publicKey = await getPublicKey()
    const { payload } = await jwtVerify(token, publicKey, {
      algorithms: ['EdDSA']
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
