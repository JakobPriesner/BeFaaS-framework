/**
 * FaaS Call Provider
 *
 * Handles function-to-function calls in serverless (FaaS) architecture.
 *
 * Call Strategy:
 * - AWS Lambda-to-Lambda: Direct invoke (bypasses API Gateway, saves cost/latency)
 * - Cross-provider or fallback: HTTP via API Gateway
 *
 * Supports multiple cloud providers: AWS, Google, Azure, TinyFaaS, OpenFaaS, OpenWhisk
 */

const _ = require('lodash')
const fetch = require('node-fetch')
const { LambdaClient, InvokeCommand } = require('@aws-sdk/client-lambda')

// Shared utilities
const { BaseCallProvider, preparePayloadWithAuth, buildCallHeaders } = require('./shared/call')
const { startRpcTiming } = require('./shared/metrics')

// Load experiment config (same as @befaas/lib)
const helper = require('@befaas/lib/helper')
const experiment = helper.loadExperiment()

// Provider endpoints from environment
const endpoints = {
  aws: process.env.AWS_LAMBDA_ENDPOINT,
  google: process.env.GOOGLE_CLOUDFUNCTION_ENDPOINT,
  azure: process.env.AZURE_FUNCTIONS_ENDPOINT,
  tinyfaas: process.env.TINYFAAS_ENDPOINT,
  openfaas: process.env.OPENFAAS_ENDPOINT,
  openwhisk: process.env.OPENWHISK_ENDPOINT
}

const publisherEndpoints = {
  aws: process.env.PUBLISHER_AWS_ENDPOINT,
  google: process.env.PUBLISHER_GOOGLE_ENDPOINT,
  azure: process.env.PUBLISHER_AZURE_ENDPOINT,
  tinyfaas: process.env.PUBLISHER_TINYFAAS_ENDPOINT
}

// ============================================================================
// Direct Lambda Invocation (AWS Lambda-to-Lambda, bypasses API Gateway)
// ============================================================================

// Check if we're running in AWS Lambda
const isLambda = !!process.env.AWS_LAMBDA_FUNCTION_NAME

// Check if direct invoke is enabled (default: true when in Lambda)
const directInvokeEnabled = process.env.DIRECT_INVOKE_ENABLED !== 'false'

// Lambda client (lazy initialized)
let lambdaClient = null

function getLambdaClient() {
  if (!lambdaClient) {
    lambdaClient = new LambdaClient({
      region: process.env.AWS_REGION || process.env.AWS_DEFAULT_REGION || 'us-east-1'
    })
  }
  return lambdaClient
}

/**
 * Get the full Lambda function name from environment variable mapping
 * Environment variables are in format: LAMBDA_FN_FUNCTIONNAME = full-function-name
 */
function getLambdaFunctionName(fn) {
  const envKey = `LAMBDA_FN_${fn.toUpperCase()}`
  return process.env[envKey] || null
}

/**
 * Check if direct Lambda invocation is available for a function
 */
function isDirectInvokeAvailable(fn) {
  if (!isLambda || !directInvokeEnabled) {
    return false
  }
  return !!getLambdaFunctionName(fn)
}

/**
 * Directly invoke another Lambda function (bypassing API Gateway)
 */
async function directInvoke(fn, payload, headers = {}) {
  const functionName = getLambdaFunctionName(fn)
  if (!functionName) {
    throw new Error(`Direct invoke not available for function: ${fn}`)
  }

  const client = getLambdaClient()

  // Wrap payload in API Gateway v2 format (HTTP API)
  const event = {
    version: '2.0',
    routeKey: 'POST /call',
    rawPath: `/${fn}/call`,
    rawQueryString: '',
    headers: {
      'content-type': 'application/json',
      ...headers
    },
    requestContext: {
      http: {
        method: 'POST',
        path: `/${fn}/call`
      },
      routeKey: 'POST /call',
      stage: '$default'
    },
    body: JSON.stringify(payload),
    isBase64Encoded: false
  }

  const command = new InvokeCommand({
    FunctionName: functionName,
    InvocationType: 'RequestResponse',
    Payload: JSON.stringify(event)
  })

  const response = await client.send(command)
  const responsePayload = JSON.parse(Buffer.from(response.Payload).toString())

  // Check for Lambda invocation errors
  if (response.FunctionError) {
    const errorMsg = `[DIRECT INVOKE ERROR] ${fn} failed: ${responsePayload.errorMessage || 'Unknown error'}`
    console.error(errorMsg)
    const error = new Error(errorMsg)
    error.functionName = fn
    error.lambdaError = responsePayload
    throw error
  }

  // Parse the API Gateway response format
  if (responsePayload.statusCode && responsePayload.statusCode >= 400) {
    const errorMsg = `[DIRECT INVOKE ERROR] ${fn} returned ${responsePayload.statusCode}: ${responsePayload.body}`
    console.error(errorMsg)
    const error = new Error(errorMsg)
    error.statusCode = responsePayload.statusCode
    error.functionName = fn
    error.responseBody = responsePayload.body
    throw error
  }

  // Parse and return the response body
  try {
    return typeof responsePayload.body === 'string'
      ? JSON.parse(responsePayload.body)
      : responsePayload.body || responsePayload
  } catch (e) {
    console.error(`[DIRECT INVOKE ERROR] ${fn} JSON parse failed: ${e.message}`)
    throw e
  }
}

// ============================================================================
// FaaS Call Provider
// ============================================================================

/**
 * FaaS-specific call provider
 * Extends BaseCallProvider with AWS direct invoke and multi-provider support
 */
class FaaSCallProvider extends BaseCallProvider {
  constructor(options = {}) {
    super(options)
    this.contextId = options.contextId || null
    this.xPair = options.xPair || null
  }

  /**
   * Check if direct Lambda invoke is available for a function
   */
  canDirectInvoke(functionName) {
    const provider = _.get(experiment, `program.functions.${functionName}.provider`)
    return provider === 'aws' && isDirectInvokeAvailable(functionName)
  }

  /**
   * FaaS always calls remotely (no in-process calls)
   */
  canCallLocally(functionName) {
    return false
  }

  /**
   * Call another function with optional Authorization header
   *
   * Automatically uses direct Lambda invocation for AWS-to-AWS calls when available,
   * falling back to HTTP via API Gateway for cross-provider calls.
   */
  async call(functionName, payload) {
    if (!_.isObject(payload)) throw new Error('payload is not an object')

    let provider = ''
    if (functionName === 'publisher') {
      const targetFn = payload.fun
      provider = _.get(experiment, `program.functions.${targetFn}.provider`)
      if (!publisherEndpoints[provider]) throw new Error('unknown publisher provider')
    } else {
      provider = _.get(experiment, `program.functions.${functionName}.provider`)
      if (!endpoints[provider]) throw new Error('unknown provider')
    }

    // Prepare payload with auth header
    const bodyWithHeaders = preparePayloadWithAuth(payload, this.authHeader)

    // Build headers
    const headers = buildCallHeaders({
      authHeader: this.authHeader,
      contextId: this.contextId,
      xPair: this.xPair
    })

    // Try direct Lambda invocation for AWS targets (bypasses API Gateway)
    if (provider === 'aws' && functionName !== 'publisher' && isDirectInvokeAvailable(functionName)) {
      return await directInvoke(functionName, bodyWithHeaders, headers)
    }

    // Fallback to HTTP via API Gateway
    const endpoint = functionName === 'publisher'
      ? `${publisherEndpoints[provider]}/call`
      : `${endpoints[provider]}/${functionName}/call`

    const res = await fetch(endpoint, {
      method: 'post',
      body: JSON.stringify(bodyWithHeaders || {}),
      headers
    })

    const text = await res.text()
    if (!res.ok) {
      const errorMsg = `[CALL ERROR] ${functionName} returned ${res.status}: ${text.substring(0, 500)}`
      console.error(errorMsg)
      const error = new Error(errorMsg)
      error.statusCode = res.status
      error.functionName = functionName
      error.responseBody = text
      throw error
    }

    try {
      return JSON.parse(text)
    } catch (e) {
      console.error(`[CALL ERROR] ${functionName} JSON parse failed: ${e.message}, body: ${text.substring(0, 200)}`)
      throw e
    }
  }
}

/**
 * Standalone call function (for backward compatibility)
 */
async function faasCall(fn, contextId, xPair, payload, authHeader = null) {
  const provider = new FaaSCallProvider({
    authHeader,
    contextId,
    xPair
  })
  return provider.call(fn, payload)
}

/**
 * Create a wrapped ctx.call function that propagates Authorization header
 * Includes metrics logging for inter-function call timing
 */
function createAuthCall(ctx, authHeader) {
  const helper = require('@befaas/lib/helper')

  return async (fn, payload) => {
    const callXPair = `${ctx.contextId}-${helper.generateRandomID()}`

    // Determine call type for metrics
    const provider = _.get(experiment, `program.functions.${fn}.provider`)
    const useDirectInvoke = provider === 'aws' && fn !== 'publisher' && isDirectInvokeAvailable(fn)
    const callType = useDirectInvoke ? 'direct' : 'http'

    // Start timing with our metrics utility (logs to CloudWatch via console.log)
    const endTiming = startRpcTiming(ctx.contextId, ctx.xPair, fn, callXPair, callType)

    let success = true
    try {
      const res = await faasCall(fn, ctx.contextId, callXPair, payload, authHeader)
      return res
    } catch (err) {
      success = false
      throw err
    } finally {
      endTiming(success)
    }
  }
}

module.exports = {
  FaaSCallProvider,
  faasCall,
  createAuthCall,
  // Backward compatibility aliases
  authCall: faasCall
}