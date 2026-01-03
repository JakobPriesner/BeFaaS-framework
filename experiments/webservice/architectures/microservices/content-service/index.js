const express = require('express')
const { configureBeFaaSLib, callService } = require('./shared/libConfig')

// Import handler functions
const getAds = require('./functions/getads')
const supportedCurrencies = require('./functions/supportedcurrencies')
const currency = require('./functions/currency')

const app = express()
app.use(express.json())

// Configure BeFaaS lib for microservices
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

      // Route internal content-service calls in-process
      if (functionName === 'getads') {
        return await getAds(eventWithHeaders, createContext(authHeader))
      }
      if (functionName === 'supportedcurrencies') {
        return await supportedCurrencies(eventWithHeaders, createContext(authHeader))
      }
      if (functionName === 'currency') {
        return await currency(eventWithHeaders, createContext(authHeader))
      }
      // External service calls go through HTTP
      return await callService(functionName, event, authHeader)
    }
  }
}

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'content-service' })
})

// Content Service Routes
app.post('/getads', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const ctx = createContext(authHeader)
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const result = await getAds(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in getads:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/supportedcurrencies', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const ctx = createContext(authHeader)
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const result = await supportedCurrencies(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in supportedcurrencies:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/currency', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const ctx = createContext(authHeader)
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const result = await currency(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in currency:', error)
    res.status(500).json({ error: error.message })
  }
})

const port = process.env.PORT || 3004

// Start server (ECS handles service registration automatically)
app.listen(port, () => {
  console.log(`Content Service listening on port ${port}`)
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