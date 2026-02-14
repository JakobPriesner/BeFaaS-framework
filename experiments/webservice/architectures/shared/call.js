/**
 * Common call interface for BeFaaS architectures
 *
 * This module defines the contract that all architecture-specific
 * call implementations must follow. Each architecture (faas, microservices,
 * monolith) provides its own optimized implementation.
 *
 * Call Strategy by Architecture:
 *
 * - FaaS:
 *   - Same provider (AWS): Direct Lambda invoke (bypasses API Gateway)
 *   - Cross-provider: HTTP via API Gateway
 *
 * - Microservices:
 *   - Same service: Direct in-process call (no network)
 *   - Different service: HTTP via internal Docker/Cloud Map DNS
 *
 * - Monolith:
 *   - Always: Direct in-process call (everything is local)
 */

/**
 * @typedef {Object} CallOptions
 * @property {string|null} authHeader - Authorization header to propagate
 * @property {string} contextId - Request context ID for tracing
 * @property {string} xPair - Request pair ID for tracing
 */

/**
 * @typedef {Object} CallContext
 * @property {function(string, Object): Promise<Object>} call - Call another function
 * @property {string} contextId - Request context ID
 */

/**
 * Base class for architecture-specific call implementations
 * Each architecture extends this with its optimized call strategy
 */
class BaseCallProvider {
  /**
   * @param {Object} options
   * @param {string|null} options.authHeader - Authorization header to propagate
   */
  constructor(options = {}) {
    this.authHeader = options.authHeader || null
  }

  /**
   * Call another function
   * @param {string} functionName - Name of the function to call
   * @param {Object} payload - Request payload
   * @returns {Promise<Object>} - Response from the called function
   */
  async call(functionName, payload) {
    throw new Error('call() must be implemented by architecture-specific provider')
  }

  /**
   * Check if a function can be called locally (in-process)
   * @param {string} functionName - Name of the function
   * @returns {boolean} - True if local call is available
   */
  canCallLocally(functionName) {
    return false
  }

  /**
   * Check if a function can be called via direct invoke (provider-specific optimization)
   * @param {string} functionName - Name of the function
   * @returns {boolean} - True if direct invoke is available
   */
  canDirectInvoke(functionName) {
    return false
  }
}

/**
 * Prepare payload with auth headers for propagation
 * @param {Object} payload - Original payload
 * @param {string|null} authHeader - Authorization header
 * @returns {Object} - Payload with headers included
 */
function preparePayloadWithAuth(payload, authHeader) {
  if (!authHeader) {
    return payload
  }
  return {
    ...payload,
    headers: { authorization: authHeader }
  }
}

/**
 * Build HTTP headers for a call
 * @param {Object} options
 * @param {string|null} options.authHeader - Authorization header
 * @param {string} options.contextId - Request context ID
 * @param {string} options.xPair - Request pair ID
 * @returns {Object} - Headers object
 */
function buildCallHeaders({ authHeader, contextId, xPair }) {
  const headers = {
    'content-type': 'application/json'
  }
  if (contextId) {
    headers['x-context'] = contextId
  }
  if (xPair) {
    headers['x-pair'] = xPair
  }
  if (authHeader) {
    headers['authorization'] = authHeader
  }
  return headers
}

module.exports = {
  BaseCallProvider,
  preparePayloadWithAuth,
  buildCallHeaders
}