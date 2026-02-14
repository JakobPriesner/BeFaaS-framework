/**
 * Metrics Logging Utility for BeFaaS
 *
 * Provides consistent BEFAAS-format logging that works with CloudWatch.
 * Uses console.log (not process.stdout.write) for reliable CloudWatch capture.
 *
 * Metrics collected:
 * - Cold start detection (per container)
 * - Handler execution timing (per request)
 * - Inter-function call timing (RPC calls)
 * - Request metadata (contextId, xPair, route)
 */

const { performance } = require('perf_hooks');
const fs = require('fs');

// Debug: log at module load time
console.log('METRICS_DEBUG_LOAD: metrics.js module loaded');

const fnName = process.env.BEFAAS_FN_NAME || 'unknown';
const deploymentId = process.env.BEFAAS_DEPLOYMENT_ID || 'unknownDeploymentId';

// Cold start tracking (per Lambda container)
let isColdStart = true;
let requestCount = 0;
const containerStartTime = Date.now();

// Log CPU info once at module load time (cold start)
try {
  const cpuInfoRaw = fs.readFileSync('/proc/cpuinfo', 'utf8');
  // Parse the first processor entry
  const fields = ['model name', 'vendor_id', 'cpu MHz', 'cache size', 'cpu cores', 'bogomips'];
  const cpuInfo = {};
  for (const field of fields) {
    const match = cpuInfoRaw.match(new RegExp(`^${field}\\s*:\\s*(.+)$`, 'm'));
    if (match) {
      cpuInfo[field.replace(/ /g, '_')] = match[1].trim();
    }
  }
  if (Object.keys(cpuInfo).length > 0) {
    // Emit using logMetric-compatible format directly since logMetric isn't defined yet
    const metric = {
      timestamp: Date.now(),
      now: performance.now(),
      deploymentId: process.env.BEFAAS_DEPLOYMENT_ID || 'unknownDeploymentId',
      fn: { name: process.env.BEFAAS_FN_NAME || 'unknown' },
      event: { cpuInfo }
    };
    console.log('BEFAAS: ' + JSON.stringify(metric));
  }
} catch (e) {
  // /proc/cpuinfo not available (e.g., macOS, Windows) - skip silently
}

/**
 * Log a metric in BEFAAS format
 * Format: "BEFAAS: {json}" - colon+space needed for CloudWatch to capture correctly
 * @param {Object} event - Event data to log
 */
function logMetric(event) {
  const metric = {
    timestamp: Date.now(),
    now: performance.now(),
    deploymentId,
    fn: { name: fnName },
    event
  };
  // Use "BEFAAS: " format (with colon+space) - plain "BEFAAS{" format gets filtered by CloudWatch
  console.log('BEFAAS: ' + JSON.stringify(metric));
}

/**
 * Log cold start once per container
 */
function logColdStartIfNeeded() {
  if (isColdStart) {
    logMetric({
      coldStart: true,
      containerStartTime
    });
    isColdStart = false;
  }
}

/**
 * Start timing a handler execution
 * @param {string} contextId - Request context ID
 * @param {string} xPair - Request pair ID
 * @param {string} route - Route being handled (e.g., "get:/", "post:/cart")
 * @returns {Function} - Call this function to end timing and log the metric
 */
function startHandlerTiming(contextId, xPair, route) {
  const startTime = performance.now();
  const isFirst = requestCount === 0;
  requestCount++;

  logColdStartIfNeeded();

  return (statusCode = 200) => {
    const durationMs = performance.now() - startTime;
    logMetric({
      contextId,
      xPair,
      handler: {
        route,
        durationMs,
        coldStart: isFirst,
        requestCount,
        statusCode
      }
    });
  };
}

/**
 * Log an inter-function (RPC) call
 * @param {string} contextId - Request context ID
 * @param {string} sourceXPair - Original request xPair
 * @param {string} targetFn - Target function being called
 * @param {string} callXPair - New xPair for this call (for linking)
 * @param {number} durationMs - Call duration in milliseconds
 * @param {boolean} success - Whether the call succeeded
 * @param {string} callType - Type of call ('direct' for Lambda invoke, 'http' for API Gateway)
 */
function logRpcCall(contextId, sourceXPair, targetFn, callXPair, durationMs, success, callType = 'unknown') {
  logMetric({
    contextId,
    xPair: sourceXPair,
    rpcOut: {
      target: targetFn,
      callXPair,
      durationMs,
      success,
      callType
    }
  });
}

/**
 * Start timing an RPC call
 * @param {string} contextId - Request context ID
 * @param {string} sourceXPair - Original request xPair
 * @param {string} targetFn - Target function being called
 * @param {string} callXPair - New xPair for this call
 * @param {string} callType - Type of call ('direct' or 'http')
 * @returns {Function} - Call with (success: boolean) to end timing and log
 */
function startRpcTiming(contextId, sourceXPair, targetFn, callXPair, callType) {
  const startTime = performance.now();

  return (success = true) => {
    const durationMs = performance.now() - startTime;
    logRpcCall(contextId, sourceXPair, targetFn, callXPair, durationMs, success, callType);
  };
}

/**
 * Log incoming RPC request (when this function is called by another)
 * @param {string} contextId - Request context ID
 * @param {string} xPair - Request pair ID
 */
function logRpcIn(contextId, xPair) {
  logColdStartIfNeeded();
  logMetric({
    contextId,
    xPair,
    rpcIn: {
      receivedAt: Date.now(),
      coldStart: requestCount === 0
    }
  });
  requestCount++;
}

/**
 * Get current metrics state (for debugging)
 */
function getMetricsState() {
  return {
    fnName,
    isColdStart,
    requestCount,
    containerStartTime,
    uptimeMs: Date.now() - containerStartTime
  };
}

module.exports = {
  logMetric,
  logColdStartIfNeeded,
  startHandlerTiming,
  logRpcCall,
  startRpcTiming,
  logRpcIn,
  getMetricsState,
  fnName
};