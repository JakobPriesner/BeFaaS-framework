const lib = require('@befaas/lib')

const _ = require('lodash')
const fs = require('fs')
const path = require('path')
const { CognitoIdentityProviderClient, InitiateAuthCommand, SignUpCommand } = require('@aws-sdk/client-cognito-identity-provider')

// Initialize Cognito client
const cognitoClient = new CognitoIdentityProviderClient({
  region: process.env.AWS_REGION || 'us-east-1'
})

const COGNITO_CLIENT_ID = process.env.COGNITO_CLIENT_ID
const COGNITO_USER_POOL_ID = process.env.COGNITO_USER_POOL_ID

let storageObj = {}

function getCookies(ctx) {
  const newMockedCookies = ctx.cookies.get('storageObj')
  if(newMockedCookies) storageObj = JSON.parse(newMockedCookies)
}

function storeCookies(ctx) {
  ctx.cookies.set('storageObj', JSON.stringify(storageObj), {overwrite: true, sameSite: true});
}

const templates = {
  home: _.template(
    fs.readFileSync(path.join(__dirname, 'html_templates', 'home.html'))
  ),
  product: _.template(
    fs.readFileSync(path.join(__dirname, 'html_templates', 'product.html'))
  ),
  cart: _.template(
    fs.readFileSync(path.join(__dirname, 'html_templates', 'cart.html'))
  ),
  order: _.template(
    fs.readFileSync(path.join(__dirname, 'html_templates', 'order.html'))
  )
}

function getSessionID (ctx) {
  if (!storageObj.sessionId) {
    storageObj.sessionId = lib.helper.generateRandomID()
  }
  return storageObj.sessionId;
}

function getUserCurrency (ctx) {
  return storageObj.userCurrency || 'EUR'
}

function getUserName (ctx) {
  return storageObj.userName || ''
}

function getUserPassword (ctx) {
  return storageObj.userPassword || ''
}

function getCartSize (ctx) {
  return _.parseInt(storageObj.cartSize) || 0
}

function increaseCartSize (ctx, inc) {
  storageObj.cartSize = getCartSize(ctx) + inc
}

function emptyCartSize (ctx) {
  storageObj.cartSize = 0
}

async function convertPrice (ctx, priceUsd) {
  if (getUserCurrency(ctx) === 'USD') {
    return priceUsd
  }
  return ctx.lib.call('currency', {
    from: priceUsd,
    toCode: getUserCurrency(ctx)
  })
}

// Should only be used if (a.currencyCode === b.currencyCode)
function addPrice (a, b) {
  const nanos = (a.nanos + b.nanos) % 1e9
  const units = Math.trunc((a.nanos + b.nanos) / 1e9) + a.units + b.units
  return {
    currencyCode: a.currencyCode,
    nanos: nanos,
    units: units
  }
}

function scalePrice (price, scalar) {
  const nanos = (price.nanos * scalar) % 1e9
  const units = Math.trunc((price.nanos * scalar) / 1e9) + price.units * scalar
  return {
    currencyCode: price.currencyCode,
    nanos: nanos,
    units: units
  }
}

function printPrice (price) {
  return (
    _.toString(price.units) +
    '.' +
    _.toString(price.nanos).substr(0, 2) +
    ' ' +
    price.currencyCode
  )
}

// Authenticate with Cognito and get JWT tokens
async function authenticateWithCognito(username, password) {
  try {
    const crypto = require('crypto')

    // Create secret hash for Cognito authentication
    const secretHash = crypto
      .createHmac('SHA256', process.env.COGNITO_CLIENT_SECRET || '')
      .update(username + COGNITO_CLIENT_ID)
      .digest('base64')

    const command = new InitiateAuthCommand({
      AuthFlow: 'USER_PASSWORD_AUTH',
      ClientId: COGNITO_CLIENT_ID,
      AuthParameters: {
        USERNAME: username,
        PASSWORD: password,
        SECRET_HASH: secretHash
      }
    })

    const response = await cognitoClient.send(command)

    return {
      success: true,
      accessToken: response.AuthenticationResult.AccessToken,
      idToken: response.AuthenticationResult.IdToken,
      refreshToken: response.AuthenticationResult.RefreshToken
    }
  } catch (error) {
    console.error('Cognito authentication error:', error.message)

    // If user doesn't exist, try to create them
    if (error.name === 'UserNotFoundException' || error.name === 'NotAuthorizedException') {
      try {
        // For demo purposes, auto-create users who don't exist
        const crypto = require('crypto')
        const secretHash = crypto
          .createHmac('SHA256', process.env.COGNITO_CLIENT_SECRET || '')
          .update(username + COGNITO_CLIENT_ID)
          .digest('base64')

        const signUpCommand = new SignUpCommand({
          ClientId: COGNITO_CLIENT_ID,
          Username: username,
          Password: password,
          SecretHash: secretHash,
          UserAttributes: [
            {
              Name: 'email',
              Value: `${username}@example.com`
            }
          ]
        })

        await cognitoClient.send(signUpCommand)

        // Try authenticating again
        const command = new InitiateAuthCommand({
          AuthFlow: 'USER_PASSWORD_AUTH',
          ClientId: COGNITO_CLIENT_ID,
          AuthParameters: {
            USERNAME: username,
            PASSWORD: password,
            SECRET_HASH: secretHash
          }
        })

        const response = await cognitoClient.send(command)

        return {
          success: true,
          accessToken: response.AuthenticationResult.AccessToken,
          idToken: response.AuthenticationResult.IdToken,
          refreshToken: response.AuthenticationResult.RefreshToken
        }
      } catch (signUpError) {
        console.error('Cognito sign up error:', signUpError.message)
        return { success: false, error: signUpError.message }
      }
    }

    return { success: false, error: error.message }
  }
}

// Get JWT token from storage
function getJWTToken() {
  return storageObj.jwtToken || ''
}

// Middleware function to set up JWT token for requests
// Called at the start of each route handler instead of using router.use()
// because @befaas/lib's serverless router doesn't support the use() method
function setupAuth(ctx) {
  getCookies(ctx)
  const jwtToken = getJWTToken()
  if (jwtToken) {
    // Set authHeader on ctx.lib so all function calls include it
    ctx.lib.authHeader = `Bearer ${jwtToken}`

    // Override ctx.lib.call to always pass the auth header
    const originalCall = ctx.lib.call.bind(ctx.lib)
    ctx.lib.call = async (fn, payload) => {
      const enrichedPayload = ctx.lib.authHeader
        ? { ...payload, _authHeader: ctx.lib.authHeader }
        : payload
      return await originalCall(fn, enrichedPayload)
    }
  }
}

module.exports = lib.serverless.router(router => {
  router.get('/', async (ctx, next) => {
    setupAuth(ctx)
    const requestId = lib.helper.generateRandomID()
    const [supportedCurrencies, productList, cats] = await Promise.all([
      ctx.lib.call('supportedcurrencies', {}),
      ctx.lib.call('listproducts', {}),
      ctx.lib.call('getads', {})
    ])

    const products = await Promise.all(
      productList.products.map(async p =>
        Object.assign({ price: await convertPrice(ctx, p.priceUsd) }, p)
      )
    )

    const options = {
      session_id: getSessionID(ctx),
      request_id: requestId,
      user_id: getUserName(ctx),
      user_currency: getUserCurrency(ctx),
      currencies: supportedCurrencies.currencyCodes,
      products,
      cart_size: getCartSize(ctx),
      banner_color: 'white', // illustrates canary deployments
      ads: cats.ads
    }
    ctx.type = 'text/html'
    ctx.body = templates.home(options)
    storeCookies(ctx)
  })

  // TODO make recommendations more meaningful? --> use categories?
  // Yes, IDs are required to be word shaped here
  router.get('/product/:productId', async (ctx, next) => {
    setupAuth(ctx)
    const productId = ctx.params.productId

    const requestId = lib.helper.generateRandomID()
    const product = await ctx.lib.call('getproduct', { id: productId })
    // error if product not found
    if (product.error) {
      ctx.type = 'application/json'
      ctx.body = product
      ctx.status = 422
      return
    }

    const [price, supportedCurrencies, recommendedIds, cat] = await Promise.all(
      [
        convertPrice(ctx, product.priceUsd),
        ctx.lib.call('supportedcurrencies', {}),
        ctx.lib.call('listrecommendations', {
          userId: getUserName(ctx),
          productIds: [productId]
        }),
        ctx.lib.call('getads', {})
      ]
    )

    product.price = price

    const options = {
      session_id: getSessionID(ctx),
      request_id: requestId,
      product: product,
      user_id: getUserName(ctx),
      user_currency: getUserCurrency(ctx),
      currencies: supportedCurrencies.currencyCodes,
      recommendations: recommendedIds.productIds,
      cart_size: getCartSize(ctx),
      ad: cat.ads[0]
    }
    ctx.type = 'text/html'
    ctx.body = templates.product(options)
    storeCookies(ctx)
  })

  router.get('/cart', async (ctx, next) => {
    setupAuth(ctx)
    const requestId = lib.helper.generateRandomID()

    const cart =
      (await ctx.lib.call('getcart', { userId: getUserName(ctx) })).items || []
    // cart.push({ productId: 'QWERTY', quantity: 2 })

    const products = await Promise.all(
      cart.map(async i =>
        Object.assign(
          {
            quantity: i.quantity
          },
          await ctx.lib.call('getproduct', { id: i.productId })
        )
      )
    )

    // Adds quantity and accordingly scaled price to each product
    const productsWithPrice = await Promise.all(
      products.map(async p =>
        Object.assign(
          {
            price: scalePrice(await convertPrice(ctx, p.priceUsd), p.quantity)
          },
          p
        )
      )
    )
    // Should actually include address in arg object here according to spec
    const [shippingCostUsd, supportedCurrencies] = await Promise.all([
      ctx.lib.call('shipmentquote', { items: cart }),
      ctx.lib.call('supportedcurrencies', {})
    ])
    const shippingCost = await convertPrice(ctx, shippingCostUsd.costUsd)

    const totalCost = _.reduce(
      _.map(productsWithPrice, 'price'),
      addPrice,
      shippingCost
    )

    const options = {
      session_id: getSessionID(ctx),
      request_id: requestId,
      items: productsWithPrice,
      user_id: getUserName(ctx),
      user_currency: getUserCurrency(ctx),
      currencies: supportedCurrencies.currencyCodes,
      cart_size: getCartSize(ctx),
      shipping_cost: shippingCost,
      total_cost: totalCost,
      credit_card_expiration_years: _.range(
        new Date().getFullYear(),
        new Date().getFullYear() + 10
      )
    }

    ctx.type = 'text/html'
    ctx.body = templates.cart(options)
    storeCookies(ctx)
  })

  router.post('/checkout', async (ctx, next) => {
    setupAuth(ctx)
    emptyCartSize(ctx)
    const requestId = lib.helper.generateRandomID()

    const order = ctx.request.body
    const [supportedCurrencies, checkoutResult] = await Promise.all([
      ctx.lib.call('supportedcurrencies', {}),
      ctx.lib.call('checkout', {
        userId: getUserName(ctx),
        userCurrency: getUserCurrency(ctx),
        address: {
          streetAddress: order.street_address,
          city: order.city,
          state: order.state,
          country: order.country,
          zipCode: _.parseInt(order.zip_code)
        },
        email: order.email,
        creditCard: {
          creditCardNumber: order.credit_card_number,
          creditCardCvv: _.parseInt(order.credit_card_cvv),
          creditCardExpirationYear: _.parseInt(
            order.credit_card_expiration_year
          ),
          creditCardExpirationMonth: _.parseInt(
            order.credit_card_expiration_month
          )
        }
      })
    ])

    const options = {
      session_id: getSessionID(ctx),
      request_id: requestId,
      user_id: getUserName(ctx),
      user_currency: getUserCurrency(ctx),
      currencies: supportedCurrencies.currencyCodes,
      cart_size: 0,
      shipping_cost: printPrice(checkoutResult.order.shippingCost),
      tracking_id: checkoutResult.order.shippingTrackingId,
      total_cost: printPrice(checkoutResult.order.totalCost),
      order_id: checkoutResult.order.orderId
    }

    ctx.type = 'text/html'
    ctx.body = templates.order(options)
    storeCookies(ctx)
  })

  router.post('/setUser', async (ctx, next) => {
    getCookies(ctx)
    const userName = ctx.request.body.userName
    const password = ctx.request.body.password

    // Call backend login function
    const authResult = await ctx.lib.call('login', { userName, password })

    if (authResult.success) {
      // Store username and JWT token in session
      emptyCartSize(ctx)
      storageObj.userName = userName
      storageObj.userPassword = password || ''
      storageObj.jwtToken = authResult.accessToken

      console.log(`User ${userName} authenticated successfully`)
    } else {
      console.error(`Failed to authenticate user ${userName}: ${authResult.error}`)
      // Store without token - will result in 403 errors for protected endpoints
      emptyCartSize(ctx)
      storageObj.userName = userName
      storageObj.userPassword = password || ''
      storageObj.jwtToken = ''
    }

    ctx.type = 'application/json'
    ctx.response.redirect('back')
    storeCookies(ctx)
  })

  router.post('/register', async (ctx, next) => {
    getCookies(ctx)
    const userName = ctx.request.body.userName
    const password = ctx.request.body.password

    // Call backend register function
    const registerResult = await ctx.lib.call('register', { userName, password })

    if (registerResult.success) {
      // After successful registration, log the user in
      const authResult = await ctx.lib.call('login', { userName, password })

      if (authResult.success) {
        emptyCartSize(ctx)
        storageObj.userName = userName
        storageObj.userPassword = password || ''
        storageObj.jwtToken = authResult.accessToken

        console.log(`User ${userName} registered and logged in successfully`)
      } else {
        console.error(`User ${userName} registered but login failed: ${authResult.error}`)
        storageObj.userName = ''
        storageObj.jwtToken = ''
      }
    } else {
      console.error(`Failed to register user ${userName}: ${registerResult.error}`)
    }

    ctx.type = 'application/json'
    ctx.response.redirect('back')
    storeCookies(ctx)
  })

  router.post('/logout', async (ctx, next) => {
    getCookies(ctx)
    emptyCartSize(ctx)
    storageObj.userName = ''
    storageObj.userPassword = ''
    storageObj.jwtToken = ''
    ctx.type = 'application/json'
    ctx.response.redirect('back')
    storeCookies(ctx)
  })

  router.post('/logoutAndLeave', async (ctx, next) => {
    getCookies(ctx)
    storageObj.userName = ''
    storageObj.userPassword = ''
    storageObj.jwtToken = ''
    emptyCartSize(ctx)
    ctx.type = 'application/json'
    ctx.response.redirect('./')
    storeCookies(ctx)
  })

  router.post('/setCurrency', async (ctx, next) => {
    getCookies(ctx)
    storageObj.userCurrency = ctx.request.body.currencyCode
    ctx.type = 'application/json'
    ctx.response.redirect('back')
    storeCookies(ctx)
  })

  router.post('/emptyCart', async (ctx, next) => {
    setupAuth(ctx)
    const userId = getUserName(ctx)
    await ctx.lib.call('emptycart', { userId: userId })
    emptyCartSize(ctx)
    ctx.type = 'application/json'
    ctx.response.redirect('back')
    storeCookies(ctx)
  })

  router.post('/addCartItem', async (ctx, next) => {
    setupAuth(ctx)
    const userName = getUserName(ctx)
    const productId = ctx.request.body.productId
    const quantity = _.parseInt(ctx.request.body.quantity)

    if (userName) {
      await ctx.lib.call('addcartitem', {
        userId: userName,
        item: {
          productId: productId,
          quantity: quantity
        }
      })
      increaseCartSize(ctx, quantity)
    }
    ctx.type = 'application/json'
    ctx.response.redirect('back')
    storeCookies(ctx)
  })
})
