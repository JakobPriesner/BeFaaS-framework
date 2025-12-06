const { CognitoJwtVerifier } = require('aws-jwt-verify');
const { performance } = require('perf_hooks');

const userPoolId = process.env.COGNITO_USER_POOL_ID;
const clientId = process.env.COGNITO_CLIENT_ID;
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

  try {
    const authHeader = event.headers?.authorization || event.headers?.Authorization;

    if (!authHeader) {
      const duration = performance.now() - startTime;
      logAuthTiming(contextId, duration, false);
      return false;
    }

    const token = authHeader.replace(/^Bearer\s+/i, '');

    const verifier = CognitoJwtVerifier.create({
      userPoolId,
      tokenUse: 'access',
      clientId,
    });

    const payload = await verifier.verify(token);

    const duration = performance.now() - startTime;
    logAuthTiming(contextId, duration, true);

    return payload;
  } catch (err) {
    const duration = performance.now() - startTime;
    logAuthTiming(contextId, duration, false);
    console.error('Error verifying JWT:', err);
    return false;
  }
}

module.exports = { verifyJWT };
