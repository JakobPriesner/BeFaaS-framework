const jwt = require('jsonwebtoken')
const bcrypt = require('bcryptjs')

const JWT_SECRET = process.env.JWT_SECRET || 'befaas-default-secret-change-in-production'
const JWT_EXPIRES_IN = process.env.JWT_EXPIRES_IN || '1h'

/**
 * Login Service for 'service-integrated-manual' auth mode.
 * Validates user against Redis and generates real JWT tokens.
 *
 * Ex Payload Body: {
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