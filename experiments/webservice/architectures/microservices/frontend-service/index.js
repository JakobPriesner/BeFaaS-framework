const express = require('express')
const cookieParser = require('cookie-parser')
const path = require('path')
const { configureBeFaaSLib, callService } = require('./shared/libConfig')

// Import API handler functions
const login = require('./functions/login')
const register = require('./functions/register')

// Import frontend HTML handlers
const frontendHandlers = require('./functions/frontend/handlers')

const app = express()
app.use(express.json())
app.use(express.urlencoded({ extended: true }))
app.use(cookieParser())

// Configure microservices
const { namespace } = configureBeFaaSLib()

// Initialize frontend templates
let templatesInitialized = false
function ensureTemplatesInitialized() {
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

// Create context object for service-to-service calls
function createContext(req, res) {
  return {
    call: callService,
    request: { body: req.body },
    params: req.params,
    cookies: {
      get: (name) => req.cookies[name],
      set: (name, value, options) => res.cookie(name, value, options)
    },
    response: {
      redirect: (url) => {
        if (url === 'back') {
          res.redirect('back')
        } else {
          res.redirect(url)
        }
      }
    },
    get type() { return res.get('Content-Type') },
    set type(v) { res.type(v) },
    get body() { return res._body },
    set body(v) { res._body = v; if (!res.headersSent) res.send(v) },
    get status() { return res.statusCode },
    set status(v) { res.status(v) }
  }
}

// Wrap frontend handler for Express
function wrapFrontendHandler(handler) {
  return async (req, res) => {
    try {
      ensureTemplatesInitialized()
      const ctx = createContext(req, res)
      await handler(ctx)
    } catch (error) {
      console.error('Error in frontend handler:', error)
      res.status(500).json({ error: error.message })
    }
  }
}

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'frontend-service' })
})

// ============================================
// FRONTEND HTML ROUTES
// ============================================
app.get('/', wrapFrontendHandler(frontendHandlers.handleHome))
app.get('/product/:productId', wrapFrontendHandler(frontendHandlers.handleProduct))
app.get('/cart', wrapFrontendHandler(frontendHandlers.handleCart))
app.post('/checkout', wrapFrontendHandler(frontendHandlers.handleCheckout))
app.post('/setUser', wrapFrontendHandler(frontendHandlers.handleSetUser))
app.post('/register', wrapFrontendHandler(frontendHandlers.handleRegister))
app.post('/logout', wrapFrontendHandler(frontendHandlers.handleLogout))
app.post('/logoutAndLeave', wrapFrontendHandler(frontendHandlers.handleLogoutAndLeave))
app.post('/setCurrency', wrapFrontendHandler(frontendHandlers.handleSetCurrency))
app.post('/emptyCart', wrapFrontendHandler(frontendHandlers.handleEmptyCart))
app.post('/addCartItem', wrapFrontendHandler(frontendHandlers.handleAddCartItem))

// ============================================
// API ROUTES (for benchmark compatibility)
// ============================================
app.post('/api/login', async (req, res) => {
  try {
    const ctx = createContext(req, res)
    const result = await login(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in login:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/api/register', async (req, res) => {
  try {
    const ctx = createContext(req, res)
    const result = await register(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in register:', error)
    res.status(500).json({ error: error.message })
  }
})

const port = process.env.PORT || 3000

// Start server (ECS handles service registration automatically)
app.listen(port, () => {
  console.log(`Frontend Service listening on port ${port}`)
  console.log(`Using Cloud Map namespace: ${namespace}`)
})

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('SIGTERM signal received: closing HTTP server')
  process.exit(0)
})

process.on('SIGINT', () => {
  console.log('SIGINT signal received: closing HTTP server')
  process.exit(0)
})

module.exports = app