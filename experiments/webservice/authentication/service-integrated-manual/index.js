const jwt = require('jsonwebtoken')
const { performance } = require('perf_hooks')

const JWT_SECRET = process.env.JWT_SECRET || 'befaas-default-secret-change-in-production'
const fnName = process.env.BEFAAS_FN_NAME || 'unknownFn'
const deploymentId = process.env.BEFAAS_DEPLOYMENT_ID || 'unknownDeploymentId'

// Log auth timing in BEFAAS format
function logAuthTiming(contextId, durationMs, success) {
  process.stdout.write(
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
      }) +
      '\n'
  )
}

/**
 * Verifies a JWT token from the Authorization header.
 * Uses manual JWT verification with jsonwebtoken library.
 *
 * @param {Object} event - The event object containing headers
 * @param {string} contextId - The context ID for logging (optional)
 * @returns {Object|false} - Returns the decoded payload if valid, false otherwise
 */
async function verifyJWT(event, contextId) {
  const startTime = performance.now()
  // Use 'unknown' as fallback contextId to ensure auth timing is always logged
  const logContextId = contextId || 'unknown'

  try {
    const authHeader = event.headers?.authorization || event.headers?.Authorization

    if (!authHeader) {
      const duration = performance.now() - startTime
      logAuthTiming(logContextId, duration, false)
      return false
    }

    const token = authHeader.replace(/^Bearer\s+/i, '')

    // Verify the JWT token
    const payload = jwt.verify(token, JWT_SECRET, {
      algorithms: ['HS256']
    })

    const duration = performance.now() - startTime
    logAuthTiming(logContextId, duration, true)

    return payload
  } catch (err) {
    const duration = performance.now() - startTime
    logAuthTiming(logContextId, duration, false)
    console.error('Error verifying JWT:', err.message)
    return false
  }
}

module.exports = { verifyJWT }
