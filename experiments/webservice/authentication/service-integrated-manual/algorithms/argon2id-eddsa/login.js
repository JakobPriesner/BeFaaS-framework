const { SignJWT, importPKCS8 } = require('jose')
const { argon2Verify } = require('hash-wasm')

const JWT_EXPIRES_IN = process.env.JWT_EXPIRES_IN || '1h'

// Cache the imported private key to avoid re-parsing on every request
let cachedPrivateKey = null

async function getPrivateKey() {
  if (cachedPrivateKey) return cachedPrivateKey
  const pem = Buffer.from(process.env.JWT_PRIVATE_KEY, 'base64').toString('utf8')
  cachedPrivateKey = await importPKCS8(pem, 'EdDSA')
  return cachedPrivateKey
}

/**
 * Login Service for 'service-integrated-manual' auth mode.
 * Validates user against Redis and generates EdDSA JWT tokens.
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

  // Verify password using argon2id
  const isValidPassword = await argon2Verify({ password, hash: user.passwordHash })
  if (!isValidPassword) {
    return { success: false, error: 'Invalid password' }
  }

  const privateKey = await getPrivateKey()
  const now = Math.floor(Date.now() / 1000)

  // Generate JWT tokens using EdDSA (Ed25519)
  const accessToken = await new SignJWT({ sub: userName, username: userName, token_use: 'access' })
    .setProtectedHeader({ alg: 'EdDSA' })
    .setIssuedAt(now)
    .setExpirationTime(JWT_EXPIRES_IN)
    .sign(privateKey)

  const idToken = await new SignJWT({ sub: userName, username: userName, token_use: 'id' })
    .setProtectedHeader({ alg: 'EdDSA' })
    .setIssuedAt(now)
    .setExpirationTime(JWT_EXPIRES_IN)
    .sign(privateKey)

  // Refresh token has longer expiry
  const refreshToken = await new SignJWT({ sub: userName, username: userName, token_use: 'refresh' })
    .setProtectedHeader({ alg: 'EdDSA' })
    .setIssuedAt(now)
    .setExpirationTime('7d')
    .sign(privateKey)

  return {
    success: true,
    accessToken,
    idToken,
    refreshToken
  }
}

module.exports = handle
