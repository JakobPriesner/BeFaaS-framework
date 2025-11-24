const express = require('express')
const lib = require('@befaas/lib')
const { configureBeFaaSLib } = require('./shared/libConfig')

// Import handler functions
const getCart = require('./functions/getcart')
const addCartItem = require('./functions/addcartitem')
const emptyCart = require('./functions/emptycart')
const cartKvStorage = require('./functions/cartkvstorage')

const app = express()
app.use(express.json())

// Configure BeFaaS lib for microservices
const { namespace } = configureBeFaaSLib()

// Initialize BeFaaS lib - this handles Redis connection internally
lib.init()

// Create context object using BeFaaS lib
function createContext() {
  return lib.context({
    call: async (functionName, event) => {
      return await lib.call(functionName, event)
    }
  })
}

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'cart-service' })
})

// Cart Service Routes
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

const port = process.env.PORT || 3002

// Start server (ECS handles service registration automatically)
app.listen(port, () => {
  console.log(`Cart Service listening on port ${port}`)
  console.log(`Connected to Redis at ${process.env.REDIS_URL || 'redis://localhost:6379'}`)
  console.log(`Using Cloud Map namespace: ${namespace}`)
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