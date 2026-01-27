/**
 * REST Handler for AWS Lambda (HTTP API v2)
 *
 * Features:
 * - Uses original BeFaaS rpcHandler pattern
 * - Conditional auth based on function configuration
 * - Fast path for public endpoints (no auth overhead)
 * - Auth propagation for downstream function calls via HTTP Authorization header
 * - Metrics logging for handler execution timing
 */

const lib = require('@befaas/lib');
const { requiresAuth } = require('./shared/authConfig');
const { createAuthCall } = require('./call');
const { startHandlerTiming, logRpcIn } = require('./shared/metrics');

/**
 * Create a REST handler with conditional authentication
 * Includes metrics logging for handler execution timing
 *
 * @param {Function} handler - The function handler (event, ctx) => result
 * @param {Object} options - Options passed to rpcHandler (e.g., { db: 'redis' })
 * @returns {Object} - Lambda handler exports
 */
function createRestHandler(handler, options = {}) {
  const functionName = process.env.BEFAAS_FN_NAME || options.functionName;
  const needsAuth = requiresAuth(functionName);

  return lib.serverless.rpcHandler(options, async (event, ctx) => {
    // Log incoming RPC request and start handler timing
    logRpcIn(ctx.contextId, ctx.xPair);
    const endTiming = startHandlerTiming(ctx.contextId, ctx.xPair, 'rpc:/call');

    let statusCode = 200;
    try {
      // Fast path: function doesn't require auth - direct pass-through
      if (!needsAuth) {
        const result = await handler(event, ctx);
        return result;
      }

      // Auth is always in headers.authorization (HTTP API v2 normalizes to lowercase)
      const authHeader = event.headers?.authorization;

      if (authHeader) {
        // Replace ctx.call with auth-propagating version
        ctx.call = createAuthCall(ctx, authHeader);
      }

      const result = await handler(event, ctx);
      return result;
    } catch (err) {
      statusCode = err.statusCode || 500;
      throw err;
    } finally {
      endTiming(statusCode);
    }
  });
}

module.exports = { createRestHandler };
