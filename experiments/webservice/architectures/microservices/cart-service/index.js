const express = require('express')
const Redis = require('ioredis')
const { configureBeFaaSLib, lib, callService } = require('./shared/libConfig')

// Import handler functions
const getCart = require('./functions/getcart')
const addCartItem = require('./functions/addcartitem')
const emptyCart = require('./functions/emptycart')
const cartKvStorage = require('./functions/cartkvstorage')

const app = express()
app.use(express.json())

// Configure microservices
const { namespace } = configureBeFaaSLib()

// Initialize Redis connection for cart storage
const redisUrl = process.env.REDIS_URL || 'redis://localhost:6379'
let redis = null

function initRedis() {
  try {
    redis = new Redis(redisUrl, {
      retryDelayOnFailover: 100,
      maxRetriesPerRequest: 3,
      lazyConnect: true
    })

    redis.on('error', (err) => {
      console.error('Redis connection error:', err.message)
    })

    redis.on('connect', () => {
      console.log('Connected to Redis')
    })

    // Connect asynchronously - don't block startup
    redis.connect().catch(err => {
      console.error('Failed to connect to Redis:', err.message)
    })
  } catch (err) {
    console.error('Failed to initialize Redis:', err.message)
  }
}

initRedis()

// Create context object with db access for cart operations
function createContext() {
  return {
    call: callService,
    db: {
      get: async (key) => {
        if (!redis) return null
        try {
          const value = await redis.get(`cart:${key}`)
          return value ? JSON.parse(value) : null
        } catch (err) {
          console.error('Redis get error:', err.message)
          return null
        }
      },
      set: async (key, value) => {
        if (!redis) return
        try {
          if (value === null) {
            await redis.del(`cart:${key}`)
          } else {
            await redis.set(`cart:${key}`, JSON.stringify(value))
          }
        } catch (err) {
          console.error('Redis set error:', err.message)
        }
      }
    }
  }
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