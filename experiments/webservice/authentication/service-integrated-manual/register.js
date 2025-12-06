const bcrypt = require('bcryptjs')

const BCRYPT_ROUNDS = parseInt(process.env.BCRYPT_ROUNDS, 10) || 10

/**
 * Register Service for 'service-integrated-manual' auth mode.
 * Stores user in Redis with bcrypt-hashed password.
 *
 * Ex Payload Body: {
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