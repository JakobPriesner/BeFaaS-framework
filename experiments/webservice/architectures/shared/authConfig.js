/**
 * Authentication configuration for BeFaaS functions
 *
 * Architecture-agnostic: defines which functions require JWT authentication.
 * Used by all architectures (faas, microservices, monolith) to determine
 * auth requirements consistently.
 *
 * Public functions skip auth processing entirely for better performance.
 */

// Functions that require JWT authentication
const authRequiredFunctions = new Set([
  'getcart',
  'addcartitem',
  'emptycart',
  'cartkvstorage',
  'checkout',
  'payment'
])

// Functions that are public (no auth required)
const publicFunctions = new Set([
  'listproducts',
  'getproduct',
  'searchproducts',
  'listrecommendations',
  'getads',
  'supportedcurrencies',
  'currency',
  'shipmentquote',
  'shiporder',
  'email',
  'frontend',
  'login',
  'register'
])

/**
 * Check if a function requires authentication
 * @param {string} functionName - Name of the function
 * @returns {boolean} - True if auth is required
 */
function requiresAuth(functionName) {
  return authRequiredFunctions.has(functionName)
}

/**
 * Check if a function is public (no auth)
 * @param {string} functionName - Name of the function
 * @returns {boolean} - True if function is public
 */
function isPublic(functionName) {
  return publicFunctions.has(functionName)
}

module.exports = {
  requiresAuth,
  isPublic,
  authRequiredFunctions,
  publicFunctions
}