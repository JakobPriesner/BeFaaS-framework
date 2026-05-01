const express = require('express')
const { configureBeFaaSLib, callService } = require('./shared/libConfig')

const getProduct = require('./functions/getproduct')
const listProducts = require('./functions/listproducts')
const searchProducts = require('./functions/searchproducts')
const listRecommendations = require('./functions/listrecommendations')

const app = express()
app.use(express.json())

const { namespace } = configureBeFaaSLib()

function createContext (authHeader = null, contextId = null, xPair = null) {
  return {
    contextId,
    xPair,
    call: async (functionName, event) => {
      // Include auth header in event for verifyJWT
      const eventWithHeaders = authHeader
        ? { ...event, headers: { authorization: authHeader } }
        : event

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
      return await callService(functionName, event, authHeader)
    }
  }
}

app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'product-service' })
})

app.post('/getproduct', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const ctx = createContext(authHeader, req.headers['x-context'], req.headers['x-pair'])
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
    const ctx = createContext(authHeader, req.headers['x-context'], req.headers['x-pair'])
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
    const ctx = createContext(authHeader, req.headers['x-context'], req.headers['x-pair'])
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
    const ctx = createContext(authHeader, req.headers['x-context'], req.headers['x-pair'])
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

app.listen(port, () => {
  console.log(`Product Service listening on port ${port}`)
  console.log(`Using Cloud Map namespace: ${namespace}`)
})

process.on('SIGTERM', () => {
  console.log('SIGTERM signal received: closing HTTP server')
  process.exit(0)
})

process.on('SIGINT', () => {
  console.log('SIGINT signal received: closing HTTP server')
  process.exit(0)
})

module.exports = app
