const express = require('express')
const Redis = require('ioredis')
const { configureBeFaaSLib, lib, callService } = require('./shared/libConfig')

const getCart = require('./functions/getcart')
const addCartItem = require('./functions/addcartitem')
const emptyCart = require('./functions/emptycart')
const cartKvStorage = require('./functions/cartkvstorage')

const app = express()
app.use(express.json())

const { namespace } = configureBeFaaSLib()

const redisUrl = process.env.REDIS_URL || 'redis://localhost:6379'
let redis = null

function initRedis () {
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

function createContext (authHeader = null, contextId = null, xPair = null) {
  const ctx = {
    contextId,
    xPair,
    call: async (functionName, event) => {
      // Include auth header in event for verifyJWT
      const eventWithHeaders = authHeader
        ? { ...event, headers: { authorization: authHeader } }
        : event

      if (functionName === 'cartkvstorage') {
        return await cartKvStorage(eventWithHeaders, createContext(authHeader))
      }
      if (functionName === 'getcart') {
        return await getCart(eventWithHeaders, createContext(authHeader))
      }
      if (functionName === 'addcartitem') {
        return await addCartItem(eventWithHeaders, createContext(authHeader))
      }
      if (functionName === 'emptycart') {
        return await emptyCart(eventWithHeaders, createContext(authHeader))
      }
      return await callService(functionName, event, authHeader)
    },
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
  return ctx
}

app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'cart-service' })
})

app.post('/getcart', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const ctx = createContext(authHeader, req.headers['x-context'], req.headers['x-pair'])
    const result = await getCart(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in getcart:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/addcartitem', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const ctx = createContext(authHeader, req.headers['x-context'], req.headers['x-pair'])
    const result = await addCartItem(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in addcartitem:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/emptycart', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const ctx = createContext(authHeader, req.headers['x-context'], req.headers['x-pair'])
    const result = await emptyCart(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in emptycart:', error)
    res.status(500).json({ error: error.message })
  }
})

app.post('/cartkvstorage', async (req, res) => {
  try {
    const authHeader = req.headers.authorization
    const event = authHeader
      ? { ...req.body, headers: { authorization: authHeader } }
      : req.body
    const ctx = createContext(authHeader, req.headers['x-context'], req.headers['x-pair'])
    const result = await cartKvStorage(event, ctx)
    res.json(result)
  } catch (error) {
    console.error('Error in cartkvstorage:', error)
    res.status(500).json({ error: error.message })
  }
})

const port = process.env.PORT || 3002

app.listen(port, () => {
  console.log(`Cart Service listening on port ${port}`)
  console.log(`Connected to Redis at ${process.env.REDIS_URL || 'redis://localhost:6379'}`)
  console.log(`Using Cloud Map namespace: ${namespace}`)
})

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
