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
function createContext() {
  return {
    call: callService
  }
}

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'product-service' })
})

// Product Service Routes
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