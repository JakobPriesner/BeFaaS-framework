const express = require('express')
const lib = require('@befaas/lib')
const { configureBeFaaSLib } = require('./shared/libConfig')

// Import handler functions
const frontend = require('./functions/frontend')

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
  res.json({ status: 'ok', service: 'frontend-service' })
})

// Frontend Service Routes
app.post('/frontend', async (req, res) => {
  try {
    const ctx = createContext()
    const result = await frontend(req.body, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in frontend:', error)
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