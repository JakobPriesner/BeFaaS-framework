const lib = require('@befaas/lib')
const handlers = require('./handlers')
const { startHandlerTiming } = require('./shared/metrics')

/**
 * FaaS Frontend - Uses @befaas/lib serverless router
 *
 * Wraps the shared handlers with FaaS-specific context adaptation.
 * The main difference is that FaaS uses ctx.lib.call() while handlers use ctx.call()
 * Includes metrics logging for handler execution timing.
 */

// Adapter to convert FaaS context (ctx.lib.call) to handler context (ctx.call)
function createHandlerContext (ctx) {
  return {
    call: async (fn, payload) => ctx.lib.call(fn, payload),
    request: ctx.request,
    params: ctx.params,
    cookies: ctx.cookies,
    response: ctx.response,
    state: ctx.state || {}, // Per-request state for session storage (prevents race conditions)
    get type () { return ctx.type },
    set type (v) { ctx.type = v },
    get body () { return ctx.body },
    set body (v) { ctx.body = v },
    get status () { return ctx.status },
    set status (v) { ctx.status = v }
  }
}

// Wrap a handler to adapt FaaS context with metrics timing
function wrapHandler (handler, routeName) {
  return async (ctx) => {
    // Start timing (also logs cold start on first request)
    const endTiming = startHandlerTiming(ctx.contextId, ctx.xPair, routeName)

    const handlerCtx = createHandlerContext(ctx)
    try {
      await handler(handlerCtx)
      endTiming(ctx.status || 200)
    } catch (err) {
      endTiming(ctx.status || 500)
      throw err
    }
  }
}

module.exports = lib.serverless.router(router => {
  router.get('/', wrapHandler(handlers.handleHome, 'get:/'))
  router.get('/product/:productId', wrapHandler(handlers.handleProduct, 'get:/product/:productId'))
  router.get('/cart', wrapHandler(handlers.handleCart, 'get:/cart'))
  router.post('/checkout', wrapHandler(handlers.handleCheckout, 'post:/checkout'))
  router.post('/setUser', wrapHandler(handlers.handleSetUser, 'post:/setUser'))
  router.post('/register', wrapHandler(handlers.handleRegister, 'post:/register'))
  router.post('/logout', wrapHandler(handlers.handleLogout, 'post:/logout'))
  router.post('/logoutAndLeave', wrapHandler(handlers.handleLogoutAndLeave, 'post:/logoutAndLeave'))
  router.post('/setCurrency', wrapHandler(handlers.handleSetCurrency, 'post:/setCurrency'))
  router.post('/emptyCart', wrapHandler(handlers.handleEmptyCart, 'post:/emptyCart'))
  router.post('/addCartItem', wrapHandler(handlers.handleAddCartItem, 'post:/addCartItem'))
})
