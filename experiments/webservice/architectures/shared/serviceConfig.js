/**
 * Service configuration for BeFaaS functions
 *
 * Architecture-agnostic: maps functions to their logical service groupings.
 * Used by microservices to determine routing, and by all architectures
 * to understand function organization.
 */

// Map functions to their owning service
const functionToService = {
  // Cart service - handles shopping cart operations
  'cartkvstorage': 'cart',
  'getcart': 'cart',
  'addcartitem': 'cart',
  'emptycart': 'cart',

  // Product service - handles product catalog
  'getproduct': 'product',
  'listproducts': 'product',
  'searchproducts': 'product',
  'listrecommendations': 'product',

  // Order service - handles checkout and fulfillment
  'checkout': 'order',
  'payment': 'order',
  'shiporder': 'order',
  'shipmentquote': 'order',
  'email': 'order',

  // Content service - handles ads and currency
  'getads': 'content',
  'supportedcurrencies': 'content',
  'currency': 'content',

  // Frontend service - handles user-facing routes and auth
  'frontend': 'frontend',
  'login': 'frontend',
  'register': 'frontend'
}

// Get all functions for a given service
const serviceFunctions = {}
for (const [fn, service] of Object.entries(functionToService)) {
  if (!serviceFunctions[service]) {
    serviceFunctions[service] = []
  }
  serviceFunctions[service].push(fn)
}

// All known services
const services = Object.keys(serviceFunctions)

// All known functions
const allFunctions = Object.keys(functionToService)

/**
 * Get the service that owns a function
 * @param {string} functionName - Name of the function
 * @returns {string|null} - Service name or null if unknown
 */
function getServiceForFunction(functionName) {
  return functionToService[functionName] || null
}

/**
 * Get all functions for a service
 * @param {string} serviceName - Name of the service
 * @returns {string[]} - Array of function names
 */
function getFunctionsForService(serviceName) {
  return serviceFunctions[serviceName] || []
}

/**
 * Check if two functions belong to the same service
 * @param {string} fn1 - First function name
 * @param {string} fn2 - Second function name
 * @returns {boolean} - True if same service
 */
function isSameService(fn1, fn2) {
  const s1 = functionToService[fn1]
  const s2 = functionToService[fn2]
  return s1 && s2 && s1 === s2
}

module.exports = {
  functionToService,
  serviceFunctions,
  services,
  allFunctions,
  getServiceForFunction,
  getFunctionsForService,
  isSameService
}