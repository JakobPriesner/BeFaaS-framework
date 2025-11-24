const lib = require('@befaas/lib')

/**
 * Configure BeFaaS lib for microservices architecture
 * Supports both AWS Cloud Map DNS and local Docker Compose networking
 */
function configureBeFaaSLib() {
  // Get Cloud Map namespace from environment (set by Terraform for AWS)
  // For local deployment, this will be undefined and we'll use Docker Compose service names
  const namespace = process.env.CLOUDMAP_NAMESPACE

  // Determine if running in AWS or local environment
  const isAWS = namespace && namespace !== 'local'

  // Build service URLs based on environment
  const serviceUrls = isAWS ? {
    // AWS Cloud Map DNS: service-name.namespace (port is the default container port)
    cart: `http://cart-service.${namespace}:3002`,
    product: `http://product-service.${namespace}:3001`,
    order: `http://order-service.${namespace}:3003`,
    content: `http://content-service.${namespace}:3004`,
    frontend: `http://frontend-service.${namespace}:3000`
  } : {
    // Docker Compose networking: service-name (from docker-compose.yml)
    cart: process.env.CART_SERVICE_URL || 'http://cart-service:3002',
    product: process.env.PRODUCT_SERVICE_URL || 'http://product-service:3001',
    order: process.env.ORDER_SERVICE_URL || 'http://order-service:3003',
    content: process.env.CONTENT_SERVICE_URL || 'http://content-service:3004',
    frontend: process.env.FRONTEND_SERVICE_URL || 'http://frontend-service:3000'
  }

  // Map function names to microservice HTTP endpoints
  const functionEndpoints = {
    // Cart service
    'cartkvstorage': `${serviceUrls.cart}/cartkvstorage`,
    'getcart': `${serviceUrls.cart}/getcart`,
    'addcartitem': `${serviceUrls.cart}/addcartitem`,
    'emptycart': `${serviceUrls.cart}/emptycart`,

    // Product service
    'getproduct': `${serviceUrls.product}/getproduct`,
    'listproducts': `${serviceUrls.product}/listproducts`,
    'searchproducts': `${serviceUrls.product}/searchproducts`,
    'listrecommendations': `${serviceUrls.product}/listrecommendations`,

    // Order service
    'checkout': `${serviceUrls.order}/checkout`,
    'payment': `${serviceUrls.order}/payment`,
    'shiporder': `${serviceUrls.order}/shiporder`,
    'shipmentquote': `${serviceUrls.order}/shipmentquote`,
    'email': `${serviceUrls.order}/email`,

    // Content service
    'getads': `${serviceUrls.content}/getads`,
    'supportedcurrencies': `${serviceUrls.content}/supportedcurrencies`,
    'currency': `${serviceUrls.content}/currency`,

    // Frontend service
    'frontend': `${serviceUrls.frontend}/frontend`
  }

  // Configure BeFaaS lib to use HTTP invoker
  lib.configure({
    invoker: 'http',
    endpoints: functionEndpoints
  })

  const environment = isAWS ? `AWS (namespace: ${namespace})` : 'local Docker Compose'
  console.log(`BeFaaS lib configured for microservices (${environment})`)

  return { namespace, functionEndpoints, isAWS }
}

module.exports = { configureBeFaaSLib }