const express = require('express')
const { configureBeFaaSLib, callService } = require('./shared/libConfig')

// Import handler functions
const getProduct = require('./functions/getproduct')
const listProducts = require('./functions/listproducts')
const searchProducts = require('./functions/searchproducts')
const listRecommendations = require('./functions/listrecommendations')

const app = express()
app.use(express.json())

// Configure microservices
const { namespace } = configureBeFaaSLib()

// Create context object for service-to-service calls
// @param {string|null} authHeader - Optional Authorization header to propagate
function createContext(authHeader = null) {
  return {
    call: async (functionName, event) => {
      // Include auth header in event for verifyJWT
      const eventWithHeaders = authHeader
        ? { ...event, headers: { authorization: authHeader } }
        : event

      // Route internal product-service calls in-process
      if (functionName === 'getproduct') {
        return await getProduct(eventWithHeaders, createContext(authHeader))
      }
      if (functionName === 'listproducts') {
        return await listProducts(eventWithHeaders, createContext(authHeader))
      }
      if (functionName === 'searchproducts') {
        return await searchProducts(eventWithHeaders, createContext(authHeader))
      }
      if (functionName === 'listrecommendations') {
        return await listRecommendations(eventWithHeaders, createContext(authHeader))
      }
      // External service calls go through HTTP
      return await callService(functionName, event, authHeader)
    }
  }
}

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'product-service' })
})

// Product Service Routes
app.post('/getproduct', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const ctx = createContext(authHeader)
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const result = await getProduct(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in getproduct:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/listproducts', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const ctx = createContext(authHeader)
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const result = await listProducts(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in listproducts:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/searchproducts', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const ctx = createContext(authHeader)
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const result = await searchProducts(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in searchproducts:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/listrecommendations', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const ctx = createContext(authHeader)
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const result = await listRecommendations(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in listrecommendations:', error)
    res.status(500).json({ error: error.message })
  }
})

const port = process.env.PORT || 3001

// Start server (ECS handles service registration automatically)
app.listen(port, () => {
  console.log(`Product Service listening on port ${port}`)
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