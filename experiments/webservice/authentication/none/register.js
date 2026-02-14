/**
 * Register Service for 'none' auth mode.
 * Stores user in Redis (like original BeFaaS benchmark) without Cognito.
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

  // Store user in Redis
  await ctx.db.set(userKey, { password })

  return {
    success: true,
    message: 'User registered successfully'
  }
}

module.exports = handle