const lib = require('@befaas/lib')
const handler = require('./handler')

module.exports = lib.serverless.router({ db: 'redis' }, (router) => {
  router.post('/call', async (ctx, next) => {
    const authFromPayload = ctx.request.body._authHeader;
    const authFromHeaders = ctx.request.headers.authorization || ctx.request.headers.Authorization;
    const authHeader = authFromPayload || authFromHeaders;

    const enrichedEvent = {
      ...ctx.request.body,
      headers: {
        ...ctx.request.headers,
        authorization: authHeader,
        Authorization: authHeader
      }
    };

    delete enrichedEvent._authHeader;

    ctx.lib.authHeader = authHeader;

    const originalCall = ctx.lib.call.bind(ctx.lib);
    ctx.lib.call = async (fn, payload) => {
      const enrichedPayload = ctx.lib.authHeader
        ? { ...payload, _authHeader: ctx.lib.authHeader }
        : payload;
      return await originalCall(fn, enrichedPayload);
    };

    ctx.body = await handler(enrichedEvent, ctx.lib);
  });
})
