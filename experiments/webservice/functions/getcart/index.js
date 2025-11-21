const lib = require('@befaas/lib')
const { verifyJWT } = require('./auth')

/**
 *
 * Returns a users cart.
 *
 * Example Payload: {
 *   "userId": "USER12"
 * }
 *
 * Example Response: {
 *   "userId": "USER12",
 *   "items": [{
 *     "productId": "QWERTY",
 *     "quantity": 7
 *   }]
 * }
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
  const cart = await ctx.call('cartkvstorage', {
    operation: 'get',
    userId: event.userId
  })
  return {
    userId: event.userId,
    items: cart.items
  }
}

module.exports = handle