/**
 * Edge-based Authentication - Register Handler
 *
 * Registers users via AWS Cognito.
 * Note: This handler does NOT create users directly - the benchmark
 * pre-registers users before running. This handler is for manual testing
 * or scenarios where new users need to be created during the experiment.
 */

const {
  CognitoIdentityProviderClient,
  SignUpCommand,
  AdminConfirmSignUpCommand
} = require('@aws-sdk/client-cognito-identity-provider');
const { performance } = require('perf_hooks');

const COGNITO_CLIENT_ID = process.env.COGNITO_CLIENT_ID;
const COGNITO_USER_POOL_ID = process.env.COGNITO_USER_POOL_ID;
const AWS_REGION = process.env.AWS_REGION || 'us-east-1';

const fnName = process.env.BEFAAS_FN_NAME || 'register';
const deploymentId = process.env.BEFAAS_DEPLOYMENT_ID || 'unknownDeploymentId';

const cognitoClient = new CognitoIdentityProviderClient({
  region: AWS_REGION
});

/**
 * Log auth timing in BEFAAS format
 */
function logAuthTiming(contextId, durationMs, success) {
  console.log(
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
            success,
            method: 'edge',
            operation: 'register'
          }
        }
      })
  );
}

/**
 * Register handler for edge auth mode.
 * Creates a new user in Cognito and auto-confirms them.
 *
 * @param {Object} event - Request event with userName, password, email
 * @param {Object} ctx - Context object
 * @returns {Object} - Registration result
 */
async function handle(event, ctx) {
  const startTime = performance.now();
  const contextId = ctx?.contextId || 'unknown';

  const { userName, password, email } = event;

  if (!userName || !password) {
    const duration = performance.now() - startTime;
    logAuthTiming(contextId, duration, false);
    return { success: false, error: 'userName and password are required' };
  }

  if (!COGNITO_CLIENT_ID || !COGNITO_USER_POOL_ID) {
    const duration = performance.now() - startTime;
    logAuthTiming(contextId, duration, false);
    return {
      success: false,
      error: 'Cognito not configured (COGNITO_CLIENT_ID or COGNITO_USER_POOL_ID missing)'
    };
  }

  try {
    // Sign up the user
    const signUpCommand = new SignUpCommand({
      ClientId: COGNITO_CLIENT_ID,
      Username: userName,
      Password: password,
      UserAttributes: email ? [{ Name: 'email', Value: email }] : []
    });

    await cognitoClient.send(signUpCommand);

    // Auto-confirm the user (for testing purposes)
    const confirmCommand = new AdminConfirmSignUpCommand({
      UserPoolId: COGNITO_USER_POOL_ID,
      Username: userName
    });

    await cognitoClient.send(confirmCommand);

    const duration = performance.now() - startTime;
    logAuthTiming(contextId, duration, true);

    return {
      success: true,
      message: 'User registered and confirmed successfully'
    };
  } catch (error) {
    const duration = performance.now() - startTime;
    logAuthTiming(contextId, duration, false);

    const errorMsg = error.message || String(error);

    // Handle specific Cognito errors
    if (error.name === 'UsernameExistsException') {
      return { success: false, error: 'User already exists' };
    }

    if (error.name === 'InvalidPasswordException') {
      return { success: false, error: 'Invalid password format' };
    }

    // Handle timeout errors
    if (errorMsg.includes('time-out') || errorMsg.includes('timeout') || errorMsg.includes('ETIMEDOUT')) {
      console.error('Cognito register timeout:', error);
      return {
        success: false,
        error: 'Registration service timeout',
        isAuthTimeout: true
      };
    }

    console.error('Register error:', errorMsg);
    return { success: false, error: errorMsg };
  }
}

module.exports = handle;