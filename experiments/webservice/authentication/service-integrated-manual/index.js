const jwt = require('jsonwebtoken')

const JWT_SECRET = process.env.JWT_SECRET || 'befaas-default-secret-change-in-production'

/**
 * Verifies a JWT token from the Authorization header.
 * Uses manual JWT verification with jsonwebtoken library.
 *
 * @param {Object} event - The event object containing headers
 * @returns {Object|false} - Returns the decoded payload if valid, false otherwise
 */
async function verifyJWT(event) {
  try {
    const authHeader = event.headers?.authorization || event.headers?.Authorization

    if (!authHeader) {
      return false
    }

    const token = authHeader.replace(/^Bearer\s+/i, '')

    // Verify the JWT token
    const payload = jwt.verify(token, JWT_SECRET, {
      algorithms: ['HS256']
    })

    return payload
  } catch (err) {
    console.error('Error verifying JWT:', err.message)
    return false
  }
}

module.exports = { verifyJWT }
