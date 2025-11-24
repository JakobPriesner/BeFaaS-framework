const express = require('express')
const lib = require('@befaas/lib')
const { configureBeFaaSLib } = require('./shared/libConfig')

// Import handler functions
const getAds = require('./functions/getads')
const supportedCurrencies = require('./functions/supportedcurrencies')
const currency = require('./functions/currency')

const app = express()
app.use(express.json())

// Configure BeFaaS lib for microservices
const { namespace } = configureBeFaaSLib()


// Create context object using BeFaaS lib
function createContext() {
  return {
    call: async (functionName, event) => {
      // Use service discovery for all external calls
      return await lib.call(functionName, event)
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