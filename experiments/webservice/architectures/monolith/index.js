const express = require('express')
const lib = require('@befaas/lib')

// Import all functions
const addCartItem = require('./functions/addcartitem')
const cartKvStorage = require('./functions/cartkvstorage')
const checkout = require('./functions/checkout')
const currency = require('./functions/currency')
const email = require('./functions/email')
const emptyCart = require('./functions/emptycart')
const frontend = require('./functions/frontend')
const getAds = require('./functions/getads')
const getCart = require('./functions/getcart')
const getProduct = require('./functions/getproduct')
const listProducts = require('./functions/listproducts')
const listRecommendations = require('./functions/listrecommendations')
const payment = require('./functions/payment')
const searchProducts = require('./functions/searchproducts')
const shipmentQuote = require('./functions/shipmentquote')
const shipOrder = require('./functions/shiporder')
const supportedCurrencies = require('./functions/supportedcurrencies')

const app = express()
app.use(express.json())

// Initialize BeFaaS lib - this handles Redis connection internally
lib.init()

// Create context object using BeFaaS lib
function createContext() {
  return lib.context({
    call: async (functionName, event) => {
      // Since this is a monolith, we can call functions directly
      const ctx = createContext()
      switch (functionName) {
        case 'addcartitem':
          return await addCartItem(event, ctx)
        case 'cartkvstorage':
          return await cartKvStorage(event, ctx)
        case 'checkout':
          return await checkout(event, ctx)
        case 'currency':
          return await currency(event, ctx)
        case 'email':
          return await email(event, ctx)
        case 'emptycart':
          return await emptyCart(event, ctx)
        case 'getads':
          return await getAds(event, ctx)
        case 'getcart':
          return await getCart(event, ctx)
        case 'getproduct':
          return await getProduct(event, ctx)
        case 'listproducts':
          return await listProducts(event, ctx)
        case 'listrecommendations':
          return await listRecommendations(event, ctx)
        case 'payment':
          return await payment(event, ctx)
        case 'searchproducts':
          return await searchProducts(event, ctx)
        case 'shipmentquote':
          return await shipmentQuote(event, ctx)
        case 'shiporder':
          return await shipOrder(event, ctx)
        case 'supportedcurrencies':
          return await supportedCurrencies(event, ctx)
        default:
          throw new Error(`Function not found: ${functionName}`)
      }
    }
  })
}

app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'monolith-service' })
})

// Cart endpoints
app.post('/getcart', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await getCart(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in getcart:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/addcartitem', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await addCartItem(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in addcartitem:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/emptycart', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await emptyCart(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in emptycart:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/cartkvstorage', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await cartKvStorage(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in cartkvstorage:', error)
    res.status(500).json({ error: error.message })
  }
})

// Product endpoints
app.post('/getproduct', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await getProduct(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in getproduct:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/listproducts', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await listProducts(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in listproducts:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/searchproducts', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await searchProducts(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in searchproducts:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/listrecommendations', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await listRecommendations(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in listrecommendations:', error)
    res.status(500).json({ error: error.message })
  }
})

// Order/Checkout endpoints
app.post('/checkout', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await checkout(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in checkout:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/payment', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await payment(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in payment:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/shipmentquote', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await shipmentQuote(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in shipmentquote:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/shiporder', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await shipOrder(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in shiporder:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/email', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await email(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in email:', error)
    res.status(500).json({ error: error.message })
  }
})

// Content endpoints
app.post('/getads', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await getAds(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in getads:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/supportedcurrencies', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await supportedCurrencies(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in supportedcurrencies:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/currency', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await currency(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in currency:', error)
    res.status(500).json({ error: error.message })
  }
})

// Frontend - uses router pattern, mount it directly
app.use('/', frontend)


const port = process.env.PORT || 3000

// Start server
app.listen(port, async () => {
  console.log(`Monolith Service listening on port ${port}`)
  console.log(`Connected to Redis at ${process.env.REDIS_URL || 'redis://localhost:6379'}`)
})

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('SIGTERM signal received: closing HTTP server')
  await lib.shutdown()
  process.exit(0)
})

process.on('SIGINT', async () => {
  console.log('SIGINT signal received: closing HTTP server')
  await lib.shutdown()
  process.exit(0)
})

module.exports = app