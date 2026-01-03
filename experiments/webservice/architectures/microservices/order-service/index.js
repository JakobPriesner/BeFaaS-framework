const express = require('express')
const { configureBeFaaSLib, callService } = require('./shared/libConfig')

// Import handler functions
const checkout = require('./functions/checkout')
const payment = require('./functions/payment')
const shipmentQuote = require('./functions/shipmentquote')
const shipOrder = require('./functions/shiporder')
const email = require('./functions/email')

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

      // Check if this is an internal service call (within order-service)
      if (functionName === 'payment') {
        return await payment(eventWithHeaders, createContext(authHeader))
      }
      if (functionName === 'shipmentquote') {
        return await shipmentQuote(eventWithHeaders, createContext(authHeader))
      }
      if (functionName === 'email') {
        return await email(eventWithHeaders, createContext(authHeader))
      }
      if (functionName === 'shiporder') {
        return await shipOrder(eventWithHeaders, createContext(authHeader))
      }

      // For external service calls, use HTTP service discovery
      return await callService(functionName, event, authHeader)
    }
  }
}

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'order-service' })
})

// Order Service Routes
app.post('/checkout', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const ctx = createContext(authHeader)
    // Include headers in event for verifyJWT
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const result = await checkout(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in checkout:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/payment', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const ctx = createContext(authHeader)
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const result = await payment(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in payment:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/shipmentquote', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const ctx = createContext(authHeader)
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const result = await shipmentQuote(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in shipmentquote:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/email', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const ctx = createContext(authHeader)
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const result = await email(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in email:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/shiporder', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const ctx = createContext(authHeader)
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const result = await shipOrder(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in shiporder:', error)
    res.status(500).json({ error: error.message })
  }
})

const port = process.env.PORT || 3003

// Start server (ECS handles service registration automatically)
app.listen(port, () => {
  console.log(`Order Service listening on port ${port}`)
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