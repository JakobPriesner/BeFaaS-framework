const Koa = require('koa')
const Router = require('@koa/router')
const bodyParser = require('koa-bodyparser')
const path = require('path')

// Import all backend functions
const addCartItem = require('./functions/addcartitem')
const cartKvStorage = require('./functions/cartkvstorage')
const checkout = require('./functions/checkout')
const currency = require('./functions/currency')
const email = require('./functions/email')
const emptyCart = require('./functions/emptycart')
const getAds = require('./functions/getads')
const getCart = require('./functions/getcart')
const getProduct = require('./functions/getproduct')
const listProducts = require('./functions/listproducts')
const listRecommendations = require('./functions/listrecommendations')
const login = require('./functions/login')
const payment = require('./functions/payment')
const register = require('./functions/register')
const searchProducts = require('./functions/searchproducts')
const shipmentQuote = require('./functions/shipmentquote')
const shipOrder = require('./functions/shiporder')
const supportedCurrencies = require('./functions/supportedcurrencies')

// Import frontend handlers
const frontendHandlers = require('./functions/frontend/handlers')

const app = new Koa()
const router = new Router()

// Defer frontend template initialization to avoid startup crashes
let templatesInitialized = false
function ensureTemplatesInitialized () {
  if (!templatesInitialized) {
    try {
      const templatesPath = path.join(__dirname, 'functions', 'frontend')
      console.log(`Initializing frontend templates from: ${templatesPath}`)
      frontendHandlers.initTemplates(templatesPath)
      templatesInitialized = true
      console.log('Frontend templates initialized successfully')
    } catch (err) {
      console.error('Failed to initialize frontend templates:', err.message)
      throw err
    }
  }
}

// Create context object with direct function calling for monolith
// Functions expect ctx.call() directly (not ctx.lib.call())
function createFunctionContext() {
  const ctx = {}
  ctx.call = async (functionName, event) => {
    // Create a new context for the called function
    const innerCtx = createFunctionContext()

    switch (functionName) {
      case 'addcartitem':
        return await addCartItem(event, innerCtx)
      case 'cartkvstorage':
        return await cartKvStorage(event, innerCtx)
      case 'checkout':
        return await checkout(event, innerCtx)
      case 'currency':
        return await currency(event, innerCtx)
      case 'email':
        return await email(event, innerCtx)
      case 'emptycart':
        return await emptyCart(event, innerCtx)
      case 'getads':
        return await getAds(event, innerCtx)
      case 'getcart':
        return await getCart(event, innerCtx)
      case 'getproduct':
        return await getProduct(event, innerCtx)
      case 'listproducts':
        return await listProducts(event, innerCtx)
      case 'listrecommendations':
        return await listRecommendations(event, innerCtx)
      case 'payment':
        return await payment(event, innerCtx)
      case 'searchproducts':
        return await searchProducts(event, innerCtx)
      case 'shipmentquote':
        return await shipmentQuote(event, innerCtx)
      case 'shiporder':
        return await shipOrder(event, innerCtx)
      case 'supportedcurrencies':
        return await supportedCurrencies(event, innerCtx)
      case 'login':
        return await login(event, innerCtx)
      case 'register':
        return await register(event, innerCtx)
      default:
        throw new Error(`Function not found: ${functionName}`)
    }
  }
  return ctx
}

// Middleware to inject function context (for ctx.call())
app.use(async (ctx, next) => {
  // Add call method directly to ctx for functions that expect ctx.call()
  const fnCtx = createFunctionContext()
  ctx.call = fnCtx.call
  await next()
})

// Use body parser
app.use(bodyParser())

// ============================================
// FRONTEND ROUTES (HTML pages)
// ============================================

// Wrap frontend handler to work with Koa context
function wrapFrontendHandler (handler) {
  return async (koaCtx) => {
    // Ensure templates are loaded before handling frontend requests
    ensureTemplatesInitialized()

    // Create handler context that bridges Koa ctx to handler expectations
    const handlerCtx = {
      call: koaCtx.call,
      request: koaCtx.request,
      params: koaCtx.params,
      cookies: koaCtx.cookies,
      response: koaCtx.response,
      get type() { return koaCtx.type },
      set type(v) { koaCtx.type = v },
      get body() { return koaCtx.body },
      set body(v) { koaCtx.body = v },
      get status() { return koaCtx.status },
      set status(v) { koaCtx.status = v }
    }
    await handler(handlerCtx)
  }
}

// Frontend HTML routes
router.get('/', wrapFrontendHandler(frontendHandlers.handleHome))
router.get('/product/:productId', wrapFrontendHandler(frontendHandlers.handleProduct))
router.get('/cart', wrapFrontendHandler(frontendHandlers.handleCart))
router.post('/checkout', wrapFrontendHandler(frontendHandlers.handleCheckout))
router.post('/setUser', wrapFrontendHandler(frontendHandlers.handleSetUser))
router.post('/register', wrapFrontendHandler(frontendHandlers.handleRegister))
router.post('/logout', wrapFrontendHandler(frontendHandlers.handleLogout))
router.post('/logoutAndLeave', wrapFrontendHandler(frontendHandlers.handleLogoutAndLeave))
router.post('/setCurrency', wrapFrontendHandler(frontendHandlers.handleSetCurrency))
router.post('/emptyCart', wrapFrontendHandler(frontendHandlers.handleEmptyCart))
router.post('/addCartItem', wrapFrontendHandler(frontendHandlers.handleAddCartItem))

// ============================================
// API ROUTES (JSON endpoints)
// ============================================

// Health check endpoint
router.get('/health', async (ctx) => {
  ctx.body = { status: 'ok', service: 'monolith-service' }
})

// Generic function call endpoint (for RPC-style calls)
router.post('/call/:functionName', async (ctx) => {
  const { functionName } = ctx.params
  try {
    const result = await ctx.call(functionName, ctx.request.body)
    ctx.body = result
  } catch (error) {
    console.error(`Error in ${functionName}:`, error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

// Direct function endpoints (API)
router.post('/api/getcart', async (ctx) => {
  try {
    const result = await getCart(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in getcart:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/addcartitem', async (ctx) => {
  try {
    const result = await addCartItem(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in addcartitem:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/emptycart', async (ctx) => {
  try {
    const result = await emptyCart(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in emptycart:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/cartkvstorage', async (ctx) => {
  try {
    const result = await cartKvStorage(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in cartkvstorage:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/getproduct', async (ctx) => {
  try {
    const result = await getProduct(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in getproduct:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/listproducts', async (ctx) => {
  try {
    const result = await listProducts(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in listproducts:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/searchproducts', async (ctx) => {
  try {
    const result = await searchProducts(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in searchproducts:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/listrecommendations', async (ctx) => {
  try {
    const result = await listRecommendations(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in listrecommendations:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/checkout', async (ctx) => {
  try {
    const result = await checkout(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in checkout:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/payment', async (ctx) => {
  try {
    const result = await payment(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in payment:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/shipmentquote', async (ctx) => {
  try {
    const result = await shipmentQuote(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in shipmentquote:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/shiporder', async (ctx) => {
  try {
    const result = await shipOrder(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in shiporder:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/email', async (ctx) => {
  try {
    const result = await email(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in email:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/getads', async (ctx) => {
  try {
    const result = await getAds(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in getads:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/supportedcurrencies', async (ctx) => {
  try {
    const result = await supportedCurrencies(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in supportedcurrencies:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/currency', async (ctx) => {
  try {
    const result = await currency(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in currency:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/login', async (ctx) => {
  try {
    const result = await login(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in login:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

router.post('/api/register', async (ctx) => {
  try {
    const result = await register(ctx.request.body, ctx)
    ctx.body = result
  } catch (error) {
    console.error('Error in register:', error)
    ctx.status = 500
    ctx.body = { error: error.message }
  }
})

// Use router
app.use(router.routes())
app.use(router.allowedMethods())

const port = process.env.PORT || 3000

// Start server
const server = app.listen(port, () => {
  console.log(`Monolith Service listening on port ${port}`)
  console.log(`Environment: ${process.env.NODE_ENV || 'development'}`)
})

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('SIGTERM signal received: closing HTTP server')
  server.close(() => {
    console.log('HTTP server closed')
    process.exit(0)
  })
})

process.on('SIGINT', () => {
  console.log('SIGINT signal received: closing HTTP server')
  server.close(() => {
    console.log('HTTP server closed')
    process.exit(0)
  })
})

module.exports = app