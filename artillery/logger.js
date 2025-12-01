const lib = require('@befaas/lib')
const fs = require('fs')
const path = require('path')
const { performance } = require('perf_hooks')


const LIB_VERSION = require('@befaas/lib/package.json').version
const deploymentId =
  process.env.BEFAAS_DEPLOYMENT_ID || 'unknownDeploymentId'

const fnName = 'artillery'

// Track registered users to avoid duplicate registration attempts
const registeredUsers = new Set()

// This is a workaround to artillery not resolving variables before the beforeRequest callback
// this results in the url field being {{ functionName }} instead of the actual url
function resolveVar(url, context) {
  const regex = /{{\s*\w+\s*}}/gm
  const match = url.match(regex)
  if (!match) return url
  for (var i = 0; i < match.length; i++) {
    const varname = match[i].match(/\w+/gm)
    url = url.replace(match[i], context.vars[varname])
  }
  return url
}

function logEvent(event) {
  console.log(
    'BEFAAS' +
    JSON.stringify({
      version: LIB_VERSION,
      deploymentId,
      timestamp: new Date().getTime(),
      now: performance.now(),
      fn: {
        id: '',
        name: fnName
      },
      event
    })
  )
}

function beforeRequest(requestParams, context, ee, next) {
  const url = resolveVar(requestParams.url, context)
  const contextId = lib.helper.generateRandomID()
  const xPair = `${contextId}-${lib.helper.generateRandomID()}`
  // Preserve existing headers (including cookies) instead of resetting them
  requestParams.headers = requestParams.headers || {}
  requestParams.headers['x-context'] = contextId
  requestParams.headers['x-pair'] = xPair
  logEvent({ url, contextId, xPair, type: 'before' })
  return next()
}

function afterResponse(requestParams, response, context, ee, next) {
  const event = {
    url: requestParams.url,
    contextId: requestParams.headers['x-context'],
    xPair: requestParams.headers['x-pair'],
    type: 'after'
  }

  // Add response validation logging when ARTILLERY_VALIDATION_MODE is enabled
  if (process.env.ARTILLERY_VALIDATION_MODE === 'true') {
    event.response = {
      statusCode: response.statusCode,
      statusMessage: response.statusMessage,
      bodyPreview: response.body ? response.body.substring(0, 50) : null // First 50 chars
    }
  }

  logEvent(event)

  return next()
}


const timestamp = Math.round(Date.now() / 1000);

function emergencyNever(requestParams, context, ee, next) {
  requestParams.formData.image = fs.createReadStream(path.resolve(__dirname, 'image-noambulance.jpg'))
  return beforeRequest(requestParams, context, ee, next);
}


function singleEmergency(requestParams, context, ee, next) {
  const now = Math.round(Date.now() / 1000);
  if (now - timestamp > 300) { // after 5 minutes (10 seconds before end of workload) send in ambulance
    requestParams.formData.image = fs.createReadStream(path.resolve(__dirname, 'image-ambulance.jpg'))
  } else {
    requestParams.formData.image = fs.createReadStream(path.resolve(__dirname, 'image-noambulance.jpg'))
  }
  return beforeRequest(requestParams, context, ee, next);
}


function emergencyScaling(requestParams, context, ee, next) {
  const now = Math.round(Date.now() / 1000);
  const phases = [1, 2, 3, 4, 5, 6, 7].map(x => x * 120)
  let emergency = false;

  for(const phase of phases) {
    if(now - timestamp > phase && now - timestamp < phase + 5) {
      emergency = true;
    }
  }

  if (emergency) { 
    requestParams.formData.image = fs.createReadStream(path.resolve(__dirname, 'image-ambulance.jpg'))
  } else {
    requestParams.formData.image = fs.createReadStream(path.resolve(__dirname, 'image-noambulance.jpg'))
  }

  return beforeRequest(requestParams, context, ee, next);
}




function emergencyEveryTwoMinutesFiveSecondsEach(requestParams, context, ee, next) {
  const now = Math.round(Date.now() / 1000);
  if (((now - timestamp) % 120) < 5) {
    requestParams.formData.image = fs.createReadStream(path.resolve(__dirname, 'image-ambulance.jpg'))
  } else {
    requestParams.formData.image = fs.createReadStream(path.resolve(__dirname, 'image-noambulance.jpg'))
  }

  return beforeRequest(requestParams, context, ee, next);
}

// Conditional registration: only register if user not already registered
function beforeRegister(requestParams, context, ee, next) {
  const userName = context.vars.userName

  if (registeredUsers.has(userName)) {
    // User already registered - mark to skip and just do login
    context.vars._skipRegister = true
    // Change to a no-op by redirecting to frontend (GET request effectively)
    // We'll handle this by making the register a no-op in the response
  }

  return beforeRequest(requestParams, context, ee, next)
}

// After registration: mark user as registered
function afterRegister(requestParams, response, context, ee, next) {
  const userName = context.vars.userName

  // If registration succeeded (302 redirect) or user was newly created, mark as registered
  if (response.statusCode === 302 || response.statusCode === 200) {
    registeredUsers.add(userName)
  }

  return afterResponse(requestParams, response, context, ee, next)
}

// Check if user needs registration (for use with Artillery's ifTrue)
function setNeedsRegistration(context, ee, next) {
  const userName = context.vars.userName
  context.vars.needsRegistration = !registeredUsers.has(userName)
  return next()
}

module.exports = {
  beforeRequest,
  afterResponse,
  singleEmergency,
  emergencyEveryTwoMinutesFiveSecondsEach,
  emergencyNever,
  emergencyScaling,
  beforeRegister,
  afterRegister,
  setNeedsRegistration
}
