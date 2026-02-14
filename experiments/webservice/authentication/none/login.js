/**
 * Login Service for 'none' auth mode.
 * Validates user against Redis (like original BeFaaS benchmark) without Cognito.
 *
 * Ex Payload Body: {
 *   "userName": "testuser",
 *   "password": "TestPassword123!"
 * }
 *
 * Response on success: {
 *   "success": true,
 *   "accessToken": "mock-access-token-<userName>",
 *   "idToken": "mock-id-token-<userName>",
 *   "refreshToken": "mock-refresh-token-<userName>"
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

  // Return mock tokens (no JWT generation needed for 'none' auth mode)
  return {
    success: true,
    accessToken: 'mock-access-token-' + userName,
    idToken: 'mock-id-token-' + userName,
    refreshToken: 'mock-refresh-token-' + userName
  }
}

module.exports = handle