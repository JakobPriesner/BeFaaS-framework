/**
 * Microservices Library Configuration
 *
 * DEPRECATED: This file re-exports from call.js for backward compatibility.
 * New code should import directly from './call' instead.
 *
 * Supports both AWS Cloud Map DNS and local Docker Compose networking.
 */

// Re-export everything from the new call module
const {
  MicroservicesCallProvider,
  callService,
  createServiceCall,
  registerLocalHandler,
  configureBeFaaSLib,
  lib,
  currentService,
  serviceUrls,
  isAWS,
  namespace,
  localHandlers,
  getFunctionEndpoint
} = require('./call')

// Re-export service config for backward compatibility
const { functionToService } = require('./arch-shared/serviceConfig')

// Build functionEndpoints map for backward compatibility
const functionEndpoints = {}
for (const functionName of Object.keys(functionToService)) {
  functionEndpoints[functionName] = getFunctionEndpoint(functionName)
}

module.exports = {
  // New exports
  MicroservicesCallProvider,
  createServiceCall,
  getFunctionEndpoint,

  // Backward compatibility exports
  configureBeFaaSLib,
  lib,
  callService,
  registerLocalHandler,
  currentService,
  functionToService,
  functionEndpoints,
  serviceUrls,
  isAWS,
  namespace,
  localHandlers
}