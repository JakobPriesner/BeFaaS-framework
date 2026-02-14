/**
 * Monolith Call Provider
 *
 * Handles function-to-function calls in monolith architecture.
 *
 * Call Strategy:
 * - Always: Direct in-process call (everything is in the same process)
 *
 * This is the most efficient call strategy as there's zero network overhead.
 * All functions are loaded at startup and called directly.
 *
 * Instrumentation:
 * - Logs RPC calls (rpcOut) for call graph analysis
 * - Logs handler timing for per-function execution analysis
 */

// Shared utilities
const { BaseCallProvider, preparePayloadWithAuth } = require('./shared/call')
const { startRpcTiming, logRpcIn, startHandlerTiming, logColdStartIfNeeded } = require('./shared/metrics')
const lib = require('@befaas/lib')

// Registry for local handlers (populated at startup)
const localHandlers = {}

// Shared database connection (initialized once, reused for all calls)
let sharedDb = null

/**
 * Initialize the shared database connection
 * @param {string} dbType - Database type ('redis' or 'memory')
 */
function initDb(dbType = 'redis') {
  if (!sharedDb) {
    const dbConnect = require('@befaas/lib/db').connect(dbType)
    // Create a simple measurement function for the db wrapper
    const measurement = (name) => () => {} // No-op measurement for monolith
    sharedDb = dbConnect(measurement)
    console.log(`Monolith database initialized: ${dbType}`)
  }
  return sharedDb
}

/**
 * Get the shared database instance
 * @returns {Object} - Database instance with get/set methods
 */
function getDb() {
  if (!sharedDb) {
    initDb('redis')
  }
  return sharedDb
}

/**
 * Register a local handler for direct invocation
 * @param {string} functionName - Name of the function
 * @param {function} handler - Handler function (event, ctx) => result
 */
function registerLocalHandler(functionName, handler) {
  localHandlers[functionName] = handler
}

/**
 * Register multiple handlers at once
 * @param {Object} handlers - Map of functionName -> handler
 */
function registerHandlers(handlers) {
  for (const [name, handler] of Object.entries(handlers)) {
    registerLocalHandler(name, handler)
  }
}

/**
 * Get all registered handler names
 * @returns {string[]} - Array of function names
 */
function getRegisteredFunctions() {
  return Object.keys(localHandlers)
}

/**
 * Monolith-specific call provider
 * All calls are direct in-process calls
 */
class MonolithCallProvider extends BaseCallProvider {
  constructor(options = {}) {
    super(options)
    this.contextId = options.contextId || null
    this.xPair = options.xPair || null
  }

  /**
   * Monolith can always call locally
   */
  canCallLocally(functionName) {
    return !!localHandlers[functionName]
  }

  /**
   * No direct invoke concept in monolith (it's all direct)
   */
  canDirectInvoke(functionName) {
    return false
  }

  /**
   * Call another function directly in-process
   *
   * This is the most efficient call path - no network, no serialization overhead.
   * Instrumented with RPC timing for call graph analysis.
   */
  async call(functionName, payload) {
    const handler = localHandlers[functionName]
    if (!handler) {
      throw new Error(`Function not found: ${functionName}. Registered: ${Object.keys(localHandlers).join(', ')}`)
    }

    // Prepare payload with auth header
    const payloadWithHeaders = preparePayloadWithAuth(payload, this.authHeader)

    // Generate new xPair for this call (for call graph linking)
    const callXPair = `${this.contextId || 'unknown'}-${lib.helper.generateRandomID()}`

    // Start RPC timing (logs rpcOut when endTiming is called)
    const endTiming = startRpcTiming(
      this.contextId || 'unknown',
      this.xPair || 'unknown',
      functionName,
      callXPair,
      'local' // Call type is 'local' for in-process monolith calls
    )

    // Log incoming RPC on the target function side
    logRpcIn(this.contextId || 'unknown', callXPair)

    // Create inner context for the called function (propagate auth and tracing)
    const innerCtx = createCallContext(this.authHeader, this.contextId, callXPair)

    try {
      const result = await handler(payloadWithHeaders, innerCtx)
      endTiming(true) // Log successful RPC call
      return result
    } catch (error) {
      endTiming(false) // Log failed RPC call
      console.error(`[LOCAL CALL ERROR] ${functionName}: ${error.message}`)
      throw error
    }
  }
}

/**
 * Create a call context with auth propagation
 * @param {string|null} authHeader - Authorization header to propagate
 * @param {string|null} contextId - Context ID for tracing (optional, generates new if not provided)
 * @param {string|null} xPair - X-Pair ID for tracing (optional, generates new if not provided)
 * @returns {Object} - Context object with call method, db, contextId, xPair
 */
function createCallContext(authHeader = null, contextId = null, xPair = null) {
  const ctxId = contextId || lib.helper.generateRandomID()
  const pair = xPair || `${ctxId}-${lib.helper.generateRandomID()}`

  // Create provider with full tracing context
  const provider = new MonolithCallProvider({
    authHeader,
    contextId: ctxId,
    xPair: pair
  })

  return {
    call: (functionName, payload) => provider.call(functionName, payload),
    db: getDb(),
    contextId: ctxId,
    xPair: pair
  }
}

/**
 * Standalone call function (for backward compatibility)
 */
async function monolithCall(functionName, payload, authHeader = null) {
  const provider = new MonolithCallProvider({ authHeader })
  return provider.call(functionName, payload)
}

/**
 * Create a call function bound to a specific auth context
 * @param {string|null} authHeader - Authorization header to propagate
 * @returns {function} - Bound call function
 */
function createMonolithCall(authHeader) {
  const provider = new MonolithCallProvider({ authHeader })
  return (functionName, payload) => provider.call(functionName, payload)
}

module.exports = {
  MonolithCallProvider,
  monolithCall,
  createMonolithCall,
  createCallContext,
  registerLocalHandler,
  registerHandlers,
  getRegisteredFunctions,
  localHandlers,
  initDb,
  getDb
}