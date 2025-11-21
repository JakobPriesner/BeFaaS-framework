const lib = require('@befaas/lib')
const { verifyJWT } = require('./auth')

/**
 *
 * Empties a users cart.
 *
 * Example Payload: {
 *   "userId": "USER12"
 * }
 *
 * Example Response: { }
 *
 */

async function handle (event, ctx) {
  // Verify JWT token
  const isValid = await verifyJWT(event)

  if (!isValid) {
    return { error: 'Unauthorized' }
  }

  if (!event.userId) {
    return { error: 'Wrong input format.' }
  }
  return await ctx.call('cartkvstorage', {
    operation: 'empty',
    userId: event.userId
  })
}

module.exports = handle
