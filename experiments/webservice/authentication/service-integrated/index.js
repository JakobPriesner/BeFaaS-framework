const { CognitoJwtVerifier } = require('aws-jwt-verify');

const userPoolId = process.env.COGNITO_USER_POOL_ID;
const clientId = process.env.COGNITO_CLIENT_ID;

async function verifyJWT(event) {
  try {
    const authHeader = event.headers?.authorization || event.headers?.Authorization;

    if (!authHeader) {
      return false;
    }

    const token = authHeader.replace(/^Bearer\s+/i, '');

    const verifier = CognitoJwtVerifier.create({
      userPoolId,
      tokenUse: 'access',
      clientId,
    });

    const payload = await verifier.verify(token);

    return payload;
  } catch (err) {
    console.error('Error verifying JWT:', err);
    return false;
  }
}

module.exports = { verifyJWT };
