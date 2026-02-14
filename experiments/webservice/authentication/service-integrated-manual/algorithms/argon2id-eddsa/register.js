const { argon2id } = require('hash-wasm')

// Argon2id parameters (tuned for Lambda: limited CPU, moderate memory)
const ARGON2_MEMORY = 65536  // 64 MB
const ARGON2_ITERATIONS = 3
const ARGON2_PARALLELISM = 1
const ARGON2_HASH_LENGTH = 32

/**
 * Register Service for 'service-integrated-manual' auth mode.
 * Stores user in Redis with argon2id-hashed password.
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

  // Hash the password with argon2id
  const salt = new Uint8Array(16)
  require('crypto').randomFillSync(salt)

  const passwordHash = await argon2id({
    password,
    salt,
    parallelism: ARGON2_PARALLELISM,
    iterations: ARGON2_ITERATIONS,
    memorySize: ARGON2_MEMORY,
    hashLength: ARGON2_HASH_LENGTH,
    outputType: 'encoded'
  })

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
