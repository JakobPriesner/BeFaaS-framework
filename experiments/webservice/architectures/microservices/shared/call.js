/**
 * Microservices Call Provider
 *
 * Handles service-to-service calls in microservices architecture.
 *
 * Call Strategy:
 * - Same service: Direct in-process call (no network overhead)
 * - Different service: HTTP via internal Docker DNS or AWS Cloud Map
 *
 * Supports both local Docker Compose and AWS ECS/Cloud Map deployments.
 */

const axios = require('axios')
const crypto = require('crypto')

// Shared utilities from architectures/shared
const { BaseCallProvider, preparePayloadWithAuth, buildCallHeaders } = require('./arch-shared/call')
const { functionToService, getServiceForFunction } = require('./arch-shared/serviceConfig')
const { startRpcTiming, logRpcIn, startHandlerTiming, logColdStartIfNeeded } = require('./arch-shared/metrics')

// Get Cloud Map namespace from environment (set by Terraform for AWS)
const namespace = process.env.CLOUDMAP_NAMESPACE

// Current service identifier (set by each microservice at startup)
const currentService = process.env.CURRENT_SERVICE || null

// Determine if running in AWS or local environment
const isAWS = namespace && namespace !== 'local'

// Registry for local handlers (populated by each service at startup)
const localHandlers = {}

// Build service URLs based on environment
const serviceUrls = isAWS ? {
  // AWS Cloud Map DNS: service-name.namespace (port is the default container port)
  cart: `http://cart-service.${namespace}:3002`,
  product: `http://product-service.${namespace}:3001`,
  order: `http://order-service.${namespace}:3003`,
  content: `http://content-service.${namespace}:3004`,
  frontend: `http://frontend-service.${namespace}:3000`
} : {
  // Docker Compose networking: service-name (from docker-compose.yml)
  cart: process.env.CART_SERVICE_URL || 'http://cart-service:3002',
  product: process.env.PRODUCT_SERVICE_URL || 'http://product-service:3001',
  order: process.env.ORDER_SERVICE_URL || 'http://order-service:3003',
  content: process.env.CONTENT_SERVICE_URL || 'http://content-service:3004',
  frontend: process.env.FRONTEND_SERVICE_URL || 'http://frontend-service:3000'
}

/**
 * Get the HTTP endpoint for a function
 */
function getFunctionEndpoint(functionName) {
  const service = getServiceForFunction(functionName)
  if (!service || !serviceUrls[service]) {
    return null
  }

  // Frontend service uses /api prefix
  if (service === 'frontend') {
    return `${serviceUrls[service]}/api/${functionName}`
  }

  return `${serviceUrls[service]}/${functionName}`
}

/**
 * Register a local handler for direct invocation within the same service
 * @param {string} functionName - Name of the function
 * @param {function} handler - Handler function
 */
function registerLocalHandler(functionName, handler) {
  localHandlers[functionName] = handler
}

/**
 * Generate a random ID (similar to lib.helper.generateRandomID)
 */
function generateRandomID() {
  return crypto.randomBytes(8).toString('hex')
}

/**
 * Microservices-specific call provider
 * Extends BaseCallProvider with same-service optimization
 * Instrumented with RPC timing for call graph analysis
 */
class MicroservicesCallProvider extends BaseCallProvider {
  constructor(options = {}) {
    super(options)
    this.currentService = options.currentService || currentService
    this.contextId = options.contextId || null
    this.xPair = options.xPair || null
  }

  /**
   * Check if a function can be called locally (same service)
   */
  canCallLocally(functionName) {
    const targetService = getServiceForFunction(functionName)
    return (
      this.currentService &&
      targetService === this.currentService &&
      !!localHandlers[functionName]
    )
  }

  /**
   * Microservices don't have "direct invoke" like Lambda
   * (but same-service calls are handled via canCallLocally)
   */
  canDirectInvoke(functionName) {
    return false
  }

  /**
   * Call another microservice function
   *
   * If the target function is in the same service, calls directly in-process.
   * Otherwise, makes an HTTP call to the target service.
   * Instrumented with RPC timing for call graph analysis.
   */
  async call(functionName, payload) {
    const payloadWithHeaders = preparePayloadWithAuth(payload, this.authHeader)

    // Generate new xPair for this call (for call graph linking)
    const callXPair = `${this.contextId || 'unknown'}-${generateRandomID()}`

    // Same-service optimization: call directly in-process
    if (this.canCallLocally(functionName)) {
      // Start RPC timing for local call
      const endTiming = startRpcTiming(
        this.contextId || 'unknown',
        this.xPair || 'unknown',
        functionName,
        callXPair,
        'local' // Call type is 'local' for in-process calls
      )

      // Log incoming RPC on the target function side
      logRpcIn(this.contextId || 'unknown', callXPair)

      try {
        const result = await localHandlers[functionName](payloadWithHeaders)
        endTiming(true)
        return result
      } catch (error) {
        endTiming(false)
        console.error(`[LOCAL CALL ERROR] ${functionName}: ${error.message}`)
        throw error
      }
    }

    // Different service: HTTP call via internal network
    const endpoint = getFunctionEndpoint(functionName)
    if (!endpoint) {
      throw new Error(`Unknown function: ${functionName}`)
    }

    // Start RPC timing for HTTP call
    const endTiming = startRpcTiming(
      this.contextId || 'unknown',
      this.xPair || 'unknown',
      functionName,
      callXPair,
      'http' // Call type is 'http' for cross-service calls
    )

    // Build headers including tracing context
    const headers = buildCallHeaders({
      authHeader: this.authHeader,
      contextId: this.contextId,
      xPair: callXPair
    })

    try {
      const response = await axios.post(endpoint, payloadWithHeaders, {
        headers,
        timeout: 30000
      })
      endTiming(true)
      return response.data
    } catch (error) {
      endTiming(false)
      console.error(`[HTTP CALL ERROR] ${functionName}: ${error.message}`)
      if (error.response) {
        return error.response.data
      }
      throw error
    }
  }
}

/**
 * Standalone call function (for backward compatibility with libConfig.js)
 */
async function callService(functionName, payload, authHeader = null) {
  const provider = new MicroservicesCallProvider({ authHeader })
  return provider.call(functionName, payload)
}

/**
 * Create a call function bound to a specific auth context
 * @param {string|null} authHeader - Authorization header to propagate
 * @returns {function} - Bound call function
 */
function createServiceCall(authHeader) {
  const provider = new MicroservicesCallProvider({ authHeader })
  return (functionName, payload) => provider.call(functionName, payload)
}

/**
 * Create a call context with auth and tracing propagation
 * @param {string|null} authHeader - Authorization header to propagate
 * @param {string|null} contextId - Context ID for tracing (optional, generates new if not provided)
 * @param {string|null} xPair - X-Pair ID for tracing (optional, generates new if not provided)
 * @returns {Object} - Context object with call method, contextId, xPair
 */
function createCallContext(authHeader = null, contextId = null, xPair = null) {
  const ctxId = contextId || generateRandomID()
  const pair = xPair || `${ctxId}-${generateRandomID()}`

  // Create provider with full tracing context
  const provider = new MicroservicesCallProvider({
    authHeader,
    contextId: ctxId,
    xPair: pair
  })

  return {
    call: (functionName, payload) => provider.call(functionName, payload),
    contextId: ctxId,
    xPair: pair
  }
}

/**
 * Configure and return lib-compatible object for microservices
 */
function configureBeFaaSLib() {
  const environment = isAWS ? `AWS (namespace: ${namespace})` : 'local Docker Compose'
  console.log(`Microservices HTTP calls configured for ${environment}`)

  return {
    namespace,
    isAWS,
    callService,
    currentService
  }
}

// Create a lib-compatible mock object
const lib = {
  call: callService,
  // These are no-ops for microservices
  init: () => console.log('lib.init() - no-op for microservices'),
  shutdown: async () => console.log('lib.shutdown() - no-op for microservices'),
  configure: () => {},
  context: (overrides = {}) => ({
    call: overrides.call || callService,
    ...overrides
  })
}

module.exports = {
  MicroservicesCallProvider,
  callService,
  createServiceCall,
  createCallContext,
  registerLocalHandler,
  configureBeFaaSLib,
  lib,
  currentService,
  serviceUrls,
  isAWS,
  namespace,
  localHandlers,
  getFunctionEndpoint,
  generateRandomID,
  // Re-export metrics functions for convenience
  startHandlerTiming,
  logColdStartIfNeeded,
  logRpcIn
}