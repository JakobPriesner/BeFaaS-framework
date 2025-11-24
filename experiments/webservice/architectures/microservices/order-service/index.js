const express = require('express')
const lib = require('@befaas/lib')
const { configureBeFaaSLib } = require('./shared/libConfig')

// Import handler functions
const checkout = require('./functions/checkout')
const payment = require('./functions/payment')
const shipmentQuote = require('./functions/shipmentquote')
const email = require('./functions/email')

const app = express()
app.use(express.json())

// Configure BeFaaS lib for microservices
const { namespace } = configureBeFaaSLib()


// Create context object using BeFaaS lib
function createContext() {
  return {
    call: async (functionName, event) => {
      // Check if this is an internal service call (within order-service)
      if (functionName === 'payment') {
        return await payment(event, createContext())
      }
      if (functionName === 'shipmentquote') {
        return await shipmentQuote(event, createContext())
      }
      if (functionName === 'email') {
        return await email(event, createContext())
      }

      // For external service calls, use service discovery
      return await lib.call(functionName, event)
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