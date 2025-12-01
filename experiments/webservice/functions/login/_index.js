process.env.BEFAAS_FN_NAME='login';const lib = require('@befaas/lib')
const { CognitoIdentityProviderClient, InitiateAuthCommand } = require('@aws-sdk/client-cognito-identity-provider')

const cognitoClient = new CognitoIdentityProviderClient({
  region: process.env.AWS_REGION || 'us-east-1'
})

const COGNITO_CLIENT_ID = process.env.COGNITO_CLIENT_ID
const COGNITO_CLIENT_SECRET = process.env.COGNITO_CLIENT_SECRET

/**
 * Login Service authenticates a user against Cognito and returns JWT tokens.
 *
 * Ex Payload Body: {
 *   "userName": "testuser",
 *   "password": "TestPassword123!"
 * }
 *
 * Response on success: {
 *   "success": true,
 *   "accessToken": "...",
 *   "idToken": "...",
 *   "refreshToken": "..."
 * }
 *
 * Response on failure: {
 *   "success": false,
 *   "error": "..."
 * }
 */
async function handle(event, ctx) {
  const { userName, password } = event

  if (!userName || !password) {
    return { success: false, error: 'userName and password are required' }
  }

  try {
    const authParameters = {
      USERNAME: userName,
      PASSWORD: password
    }

    // Only include SECRET_HASH if client secret is configured
    if (COGNITO_CLIENT_SECRET) {
      const crypto = require('crypto')
      const secretHash = crypto
        .createHmac('SHA256', COGNITO_CLIENT_SECRET)
        .update(userName + COGNITO_CLIENT_ID)
        .digest('base64')
      authParameters.SECRET_HASH = secretHash
    }

    const command = new InitiateAuthCommand({
      AuthFlow: 'USER_PASSWORD_AUTH',
      ClientId: COGNITO_CLIENT_ID,
      AuthParameters: authParameters
    })

    const response = await cognitoClient.send(command)

    return {
      success: true,
      accessToken: response.AuthenticationResult.AccessToken,
      idToken: response.AuthenticationResult.IdToken,
      refreshToken: response.AuthenticationResult.RefreshToken
    }
  } catch (error) {
    console.error('Login error:', error.message)
    return { success: false, error: error.message }
  }
}

module.exports = handle
