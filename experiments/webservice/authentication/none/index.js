const { performance } = require('perf_hooks');

const fnName = process.env.BEFAAS_FN_NAME || 'unknownFn';
const deploymentId = process.env.BEFAAS_DEPLOYMENT_ID || 'unknownDeploymentId';

// Log auth timing in BEFAAS format
function logAuthTiming(contextId, durationMs, success) {
  process.stdout.write(
    'BEFAAS' +
      JSON.stringify({
        timestamp: new Date().getTime(),
        now: performance.now(),
        deploymentId,
        fn: { name: fnName },
        event: {
          contextId,
          authCheck: {
            durationMs,
            success
          }
        }
      }) +
      '\n'
  );
}

async function verifyJWT(event, contextId) {
  const startTime = performance.now();
  const duration = performance.now() - startTime;
  logAuthTiming(contextId, duration, true);
  return true;
}

module.exports = { verifyJWT };