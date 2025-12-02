/**
 * Frontend Handlers - Shared business logic for FaaS and Monolith architectures
 *
 * Each handler accepts a normalized context object:
 * - ctx.call(functionName, payload) - calls another function
 * - ctx.request.body - request body (for POST)
 * - ctx.params - route parameters
 * - ctx.cookies - cookie access
 * - ctx.type - response type setter
 * - ctx.body - response body setter
 * - ctx.response.redirect - redirect function
 */

const lib = require('@befaas/lib')
const _ = require('lodash')
const fs = require('fs')
const path = require('path')

// Session storage object (per-request, loaded from cookies)
let storageObj = {}

// Load templates - path resolution works for both FaaS and monolith builds
function loadTemplates (basePath) {
  const templatesPath = basePath || __dirname
  const templatesDir = path.join(templatesPath, 'html_templates')

  // Check if templates directory exists
  if (!fs.existsSync(templatesDir)) {
    console.error(`Templates directory not found: ${templatesDir}`)
    console.error(`Current directory: ${__dirname}`)
    console.error(`Base path: ${basePath}`)
    throw new Error(`Templates directory not found: ${templatesDir}`)
  }

  const templateFiles = ['home.html', 'product.html', 'cart.html', 'order.html']
  for (const file of templateFiles) {
    const filePath = path.join(templatesDir, file)
    if (!fs.existsSync(filePath)) {
      console.error(`Template file not found: ${filePath}`)
      throw new Error(`Template file not found: ${filePath}`)
    }
  }

  return {
    home: _.template(
      fs.readFileSync(path.join(templatesDir, 'home.html'))
    ),
    product: _.template(
      fs.readFileSync(path.join(templatesDir, 'product.html'))
    ),
    cart: _.template(
      fs.readFileSync(path.join(templatesDir, 'cart.html'))
    ),
    order: _.template(
      fs.readFileSync(path.join(templatesDir, 'order.html'))
    )
  }
}

// Default templates (loaded on first use)
let templates = null
function getTemplates(basePath) {
  if (!templates) {
    templates = loadTemplates(basePath)
  }
  return templates
}

// Initialize templates with custom path (for monolith)
function initTemplates(basePath) {
  templates = loadTemplates(basePath)
}

// Cookie helpers
function getCookies(ctx) {
  const newMockedCookies = ctx.cookies.get('storageObj')
  if (newMockedCookies) storageObj = JSON.parse(newMockedCookies)
}

function storeCookies(ctx) {
  ctx.cookies.set('storageObj', JSON.stringify(storageObj), { overwrite: true, sameSite: true })
}

// Session helpers
function getSessionID(ctx) {
  if (!storageObj.sessionId) {
    storageObj.sessionId = lib.helper.generateRandomID()
  }
  return storageObj.sessionId
}

function getUserCurrency(ctx) {
  return storageObj.userCurrency || 'EUR'
}

function getUserName(ctx) {
  return storageObj.userName || ''
}

function getCartSize(ctx) {
  return _.parseInt(storageObj.cartSize) || 0
}

function increaseCartSize(ctx, inc) {
  storageObj.cartSize = getCartSize(ctx) + inc
}

function emptyCartSize(ctx) {
  storageObj.cartSize = 0
}

function getJWTToken() {
  return storageObj.jwtToken || ''
}

// Price helpers
async function convertPrice(ctx, priceUsd) {
  if (getUserCurrency(ctx) === 'USD') {
    return priceUsd
  }
  return ctx.call('currency', {
    from: priceUsd,
    toCode: getUserCurrency(ctx)
  })
}

function addPrice(a, b) {
  const nanos = (a.nanos + b.nanos) % 1e9
  const units = Math.trunc((a.nanos + b.nanos) / 1e9) + a.units + b.units
  return {
    currencyCode: a.currencyCode,
    nanos: nanos,
    units: units
  }
}

function scalePrice(price, scalar) {
  const nanos = (price.nanos * scalar) % 1e9
  const units = Math.trunc((price.nanos * scalar) / 1e9) + price.units * scalar
  return {
    currencyCode: price.currencyCode,
    nanos: nanos,
    units: units
  }
}

function printPrice(price) {
  return (
    _.toString(price.units) +
    '.' +
    _.toString(price.nanos).substr(0, 2) +
    ' ' +
    price.currencyCode
  )
}

// Auth setup - enriches ctx.call with auth header if JWT token exists
function setupAuth(ctx) {
  getCookies(ctx)
  const jwtToken = getJWTToken()
  if (jwtToken) {
    const originalCall = ctx.call.bind(ctx)
    ctx.call = async (fn, payload) => {
      const enrichedPayload = { ...payload, _authHeader: `Bearer ${jwtToken}` }
      return await originalCall(fn, enrichedPayload)
    }
  }
}

// Route Handlers

async function handleHome(ctx) {
  setupAuth(ctx)
  const requestId = lib.helper.generateRandomID()
  const [supportedCurrencies, productList, cats] = await Promise.all([
    ctx.call('supportedcurrencies', {}),
    ctx.call('listproducts', {}),
    ctx.call('getads', {})
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
    banner_color: 'white',
    ads: cats.ads
  }
  ctx.type = 'text/html'
  ctx.body = getTemplates().home(options)
  storeCookies(ctx)
}

async function handleProduct(ctx) {
  setupAuth(ctx)
  const productId = ctx.params.productId

  const requestId = lib.helper.generateRandomID()
  const product = await ctx.call('getproduct', { id: productId })

  if (product.error) {
    ctx.type = 'application/json'
    ctx.body = product
    ctx.status = 422
    return
  }

  const [price, supportedCurrencies, recommendedIds, cat] = await Promise.all([
    convertPrice(ctx, product.priceUsd),
    ctx.call('supportedcurrencies', {}),
    ctx.call('listrecommendations', {
      userId: getUserName(ctx),
      productIds: [productId]
    }),
    ctx.call('getads', {})
  ])

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
  ctx.body = getTemplates().product(options)
  storeCookies(ctx)
}

async function handleCart(ctx) {
  setupAuth(ctx)
  const requestId = lib.helper.generateRandomID()

  const cart = (await ctx.call('getcart', { userId: getUserName(ctx) })).items || []

  const products = await Promise.all(
    cart.map(async i =>
      Object.assign(
        { quantity: i.quantity },
        await ctx.call('getproduct', { id: i.productId })
      )
    )
  )

  const productsWithPrice = await Promise.all(
    products.map(async p =>
      Object.assign(
        { price: scalePrice(await convertPrice(ctx, p.priceUsd), p.quantity) },
        p
      )
    )
  )

  const [shippingCostUsd, supportedCurrencies] = await Promise.all([
    ctx.call('shipmentquote', { items: cart }),
    ctx.call('supportedcurrencies', {})
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
  ctx.body = getTemplates().cart(options)
  storeCookies(ctx)
}

async function handleCheckout(ctx) {
  setupAuth(ctx)
  emptyCartSize(ctx)
  const requestId = lib.helper.generateRandomID()

  const order = ctx.request.body
  const [supportedCurrencies, checkoutResult] = await Promise.all([
    ctx.call('supportedcurrencies', {}),
    ctx.call('checkout', {
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
        creditCardExpirationYear: _.parseInt(order.credit_card_expiration_year),
        creditCardExpirationMonth: _.parseInt(order.credit_card_expiration_month)
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
  ctx.body = getTemplates().order(options)
  storeCookies(ctx)
}

async function handleSetUser(ctx) {
  getCookies(ctx)
  const userName = ctx.request.body.userName
  const password = ctx.request.body.password

  const authResult = await ctx.call('login', { userName, password })

  if (authResult.success) {
    emptyCartSize(ctx)
    storageObj.userName = userName
    storageObj.userPassword = password || ''
    storageObj.jwtToken = authResult.accessToken
    console.log(`User ${userName} authenticated successfully`)
  } else {
    console.error(`Failed to authenticate user ${userName}: ${authResult.error}`)
    emptyCartSize(ctx)
    storageObj.userName = userName
    storageObj.userPassword = password || ''
    storageObj.jwtToken = ''
  }

  ctx.type = 'application/json'
  ctx.response.redirect('back')
  storeCookies(ctx)
}

async function handleRegister(ctx) {
  getCookies(ctx)
  const userName = ctx.request.body.userName
  const password = ctx.request.body.password

  const registerResult = await ctx.call('register', { userName, password })

  if (registerResult.success) {
    const authResult = await ctx.call('login', { userName, password })
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
    const authResult = await ctx.call('login', { userName, password })
    if (authResult.success) {
      emptyCartSize(ctx)
      storageObj.userName = userName
      storageObj.userPassword = password || ''
      storageObj.jwtToken = authResult.accessToken
      console.log(`User ${userName} already existed, logged in successfully`)
    } else {
      console.error(`Failed to login existing user ${userName}: ${authResult.error}`)
      storageObj.jwtToken = ''
    }
  }

  ctx.type = 'application/json'
  ctx.response.redirect('back')
  storeCookies(ctx)
}

async function handleLogout(ctx) {
  getCookies(ctx)
  emptyCartSize(ctx)
  storageObj.userName = ''
  storageObj.userPassword = ''
  storageObj.jwtToken = ''
  ctx.type = 'application/json'
  ctx.response.redirect('back')
  storeCookies(ctx)
}

async function handleLogoutAndLeave(ctx) {
  getCookies(ctx)
  storageObj.userName = ''
  storageObj.userPassword = ''
  storageObj.jwtToken = ''
  emptyCartSize(ctx)
  ctx.type = 'application/json'
  ctx.response.redirect('./')
  storeCookies(ctx)
}

async function handleSetCurrency(ctx) {
  getCookies(ctx)
  storageObj.userCurrency = ctx.request.body.currencyCode
  ctx.type = 'application/json'
  ctx.response.redirect('back')
  storeCookies(ctx)
}

async function handleEmptyCart(ctx) {
  setupAuth(ctx)
  const userId = getUserName(ctx)
  await ctx.call('emptycart', { userId: userId })
  emptyCartSize(ctx)
  ctx.type = 'application/json'
  ctx.response.redirect('back')
  storeCookies(ctx)
}

async function handleAddCartItem(ctx) {
  setupAuth(ctx)
  const userName = getUserName(ctx)
  const productId = ctx.request.body.productId
  const quantity = _.parseInt(ctx.request.body.quantity)

  if (userName) {
    await ctx.call('addcartitem', {
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
}

module.exports = {
  // Initialization
  initTemplates,
  getTemplates,

  // Handlers
  handleHome,
  handleProduct,
  handleCart,
  handleCheckout,
  handleSetUser,
  handleRegister,
  handleLogout,
  handleLogoutAndLeave,
  handleSetCurrency,
  handleEmptyCart,
  handleAddCartItem,

  // Helpers (exported for potential reuse)
  setupAuth,
  getCookies,
  storeCookies,
  convertPrice,
  addPrice,
  scalePrice,
  printPrice
}