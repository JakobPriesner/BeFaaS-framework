const lib = require('@befaas/lib')
const handler = require('./handler')

module.exports = lib.serverless.rpcHandler({ db: 'redis' }, async (event, ctx) => {
  return await handler.handle(event, ctx);
})
