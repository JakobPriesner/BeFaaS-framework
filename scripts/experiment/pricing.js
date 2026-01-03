const fs = require('fs')
const path = require('path')
const { execSync } = require('child_process')
const {
  CloudWatchClient,
  GetMetricDataCommand
} = require('@aws-sdk/client-cloudwatch')
const { logSection } = require('./utils')

// ============================================================================
// PRICING CONSTANTS (us-east-1, December 2024) - VALIDATED
// ============================================================================

const PRICING = {
  // AWS Lambda
  lambda: {
    requestCostPerMillion: 0.20, // $0.20 per 1M requests
    durationCostPerGBSecond: 0.0000166667, // Per GB-second
    freeRequestsPerMonth: 1000000,
    freeGBSecondsPerMonth: 400000
  },

  // API Gateway HTTP API (v2) - Used by FaaS architecture
  apiGatewayHttp: {
    requestCostPerMillion: 1.00 // $1.00 per million (first 300M)
  },

  // AWS Fargate
  fargate: {
    vCpuPerHour: 0.04048, // $0.04048 per vCPU per hour
    memoryGBPerHour: 0.004445 // $0.004445 per GB per hour
  },

  // Application Load Balancer
  alb: {
    hourlyRate: 0.0225, // $0.0225 per hour
    lcuPerHour: 0.008 // $0.008 per LCU-hour
  },

  // Redis on EC2 (t3a.medium)
  redis: {
    t3aMediumPerHour: 0.0416 // $0.0416/hour
  },

  // Cognito (tiered pricing)
  cognito: {
    mauFirst50k: 0.0055, // $0.0055 per MAU (first 50K)
    mauNext50k: 0.0046, // $0.0046 per MAU (50K-100K)
    mauNext900k: 0.00325, // $0.00325 per MAU (100K-1M)
    mauOver1m: 0.0025 // $0.0025 per MAU (over 1M)
  }
}

// ============================================================================
// TERRAFORM OUTPUT HELPERS
// ============================================================================

function getTerraformOutputs (infraDir) {
  try {
    const output = execSync('terraform output -json', {
      cwd: infraDir,
      encoding: 'utf8'
    })
    const outputs = JSON.parse(output)
    const result = {}
    for (const [key, val] of Object.entries(outputs)) {
      result[key] = val.value
    }
    return result
  } catch (error) {
    console.log(`Could not get Terraform outputs from ${infraDir}: ${error.message}`)
    return null
  }
}

// ============================================================================
// METRIC PROCESSING HELPERS
// ============================================================================

function processMetricResults (results) {
  const metrics = {}

  for (const result of results) {
    const timestamps = result.Timestamps || []
    const values = result.Values || []

    const dataPoints = timestamps.map((ts, i) => ({
      timestamp: ts.toISOString(),
      value: values[i]
    }))

    dataPoints.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))

    metrics[result.Label] = {
      id: result.Id,
      status: result.StatusCode,
      data_points: dataPoints,
      values: values,
      summary: values.length > 0
        ? {
            count: values.length,
            sum: values.reduce((a, b) => a + b, 0),
            min: Math.min(...values),
            max: Math.max(...values),
            avg: values.reduce((a, b) => a + b, 0) / values.length
          }
        : null
    }
  }

  return metrics
}

// ============================================================================
// COST CALCULATION FUNCTIONS
// ============================================================================

function calculateLambdaCost (metrics, memoryMb) {
  const memoryGb = memoryMb / 1024

  let totalInvocations = 0
  let totalDurationMs = 0
  const functionCosts = {}

  // Aggregate per-function metrics
  for (const [label, data] of Object.entries(metrics)) {
    if (label.startsWith('Lambda Invocations - ')) {
      const fnName = label.replace('Lambda Invocations - ', '')
      const invocations = data.values.reduce((a, b) => a + b, 0)
      totalInvocations += invocations

      if (!functionCosts[fnName]) functionCosts[fnName] = { invocations: 0, duration_ms: 0 }
      functionCosts[fnName].invocations = invocations
    }

    if (label.startsWith('Lambda Duration - ')) {
      const fnName = label.replace('Lambda Duration - ', '')
      const durationMs = data.values.reduce((a, b) => a + b, 0)
      totalDurationMs += durationMs

      if (!functionCosts[fnName]) functionCosts[fnName] = { invocations: 0, duration_ms: 0 }
      functionCosts[fnName].duration_ms = durationMs
    }
  }

  // Calculate costs
  const gbSeconds = (totalDurationMs / 1000) * memoryGb
  const requestCost = (totalInvocations / 1000000) * PRICING.lambda.requestCostPerMillion
  const computeCost = gbSeconds * PRICING.lambda.durationCostPerGBSecond

  // Per-function costs
  for (const [fn, data] of Object.entries(functionCosts)) {
    const fnGbSeconds = (data.duration_ms / 1000) * memoryGb
    data.gb_seconds = fnGbSeconds
    data.request_cost = (data.invocations / 1000000) * PRICING.lambda.requestCostPerMillion
    data.compute_cost = fnGbSeconds * PRICING.lambda.durationCostPerGBSecond
    data.total_cost = data.request_cost + data.compute_cost
  }

  return {
    total_invocations: totalInvocations,
    total_duration_ms: totalDurationMs,
    gb_seconds: gbSeconds,
    memory_gb: memoryGb,
    request_cost: requestCost,
    compute_cost: computeCost,
    total_cost: requestCost + computeCost,
    per_function: functionCosts,
    pricing_used: PRICING.lambda
  }
}

function calculateApiGatewayCost (metrics) {
  let totalRequests = 0

  for (const [label, data] of Object.entries(metrics)) {
    if (label === 'API Gateway Request Count') {
      totalRequests = data.values.reduce((a, b) => a + b, 0)
    }
  }

  const cost = (totalRequests / 1000000) * PRICING.apiGatewayHttp.requestCostPerMillion

  return {
    total_requests: totalRequests,
    cost: cost,
    pricing_used: PRICING.apiGatewayHttp
  }
}

function calculateFargateCost (metrics, taskCpu, taskMemory, durationHours, serviceLabel = 'ECS Running Tasks') {
  // Get average running task count
  let avgRunningTasks = 1

  for (const [label, data] of Object.entries(metrics)) {
    if (label === serviceLabel && data.values.length > 0) {
      avgRunningTasks = data.values.reduce((a, b) => a + b, 0) / data.values.length
    }
  }

  const vCpuHours = (taskCpu / 1024) * durationHours * avgRunningTasks
  const memoryGbHours = (taskMemory / 1024) * durationHours * avgRunningTasks

  const vCpuCost = vCpuHours * PRICING.fargate.vCpuPerHour
  const memoryCost = memoryGbHours * PRICING.fargate.memoryGBPerHour

  return {
    task_cpu: taskCpu,
    task_memory_mb: taskMemory,
    avg_running_tasks: avgRunningTasks,
    vcpu_hours: vCpuHours,
    memory_gb_hours: memoryGbHours,
    vcpu_cost: vCpuCost,
    memory_cost: memoryCost,
    total_cost: vCpuCost + memoryCost,
    pricing_used: PRICING.fargate
  }
}

function calculateAlbCost (metrics, durationHours) {
  // Hourly base cost
  const hourlyCost = durationHours * PRICING.alb.hourlyRate

  // LCU calculation (simplified - uses highest dimension)
  // AWS charges for the highest of: new connections, active connections, processed bytes, rule evaluations
  let maxLcu = 1

  for (const [label, data] of Object.entries(metrics)) {
    if (label === 'ALB New Connections' && data.values.length > 0) {
      const newConnPerSec = data.values.reduce((a, b) => a + b, 0) / (durationHours * 3600)
      maxLcu = Math.max(maxLcu, newConnPerSec / 25) // 25 new connections/sec = 1 LCU
    }
    if (label === 'ALB Active Connections' && data.values.length > 0) {
      const avgActive = data.values.reduce((a, b) => a + b, 0) / data.values.length
      maxLcu = Math.max(maxLcu, avgActive / 3000) // 3000 active connections = 1 LCU
    }
    if (label === 'ALB Processed Bytes' && data.values.length > 0) {
      const gbPerHour = (data.values.reduce((a, b) => a + b, 0) / (1024 * 1024 * 1024)) / durationHours
      maxLcu = Math.max(maxLcu, gbPerHour) // 1 GB/hour = 1 LCU
    }
  }

  const lcuCost = maxLcu * durationHours * PRICING.alb.lcuPerHour

  return {
    duration_hours: durationHours,
    hourly_cost: hourlyCost,
    estimated_lcu: maxLcu,
    lcu_cost: lcuCost,
    total_cost: hourlyCost + lcuCost,
    pricing_used: PRICING.alb
  }
}

function calculateCognitoCost (mau) {
  let cost = 0
  let remaining = mau

  // First 50K
  if (remaining > 0) {
    const tier1 = Math.min(remaining, 50000)
    cost += tier1 * PRICING.cognito.mauFirst50k
    remaining -= tier1
  }

  // Next 50K (50K-100K)
  if (remaining > 0) {
    const tier2 = Math.min(remaining, 50000)
    cost += tier2 * PRICING.cognito.mauNext50k
    remaining -= tier2
  }

  // Next 900K (100K-1M)
  if (remaining > 0) {
    const tier3 = Math.min(remaining, 900000)
    cost += tier3 * PRICING.cognito.mauNext900k
    remaining -= tier3
  }

  // Over 1M
  if (remaining > 0) {
    cost += remaining * PRICING.cognito.mauOver1m
  }

  return {
    mau: mau,
    cost: cost,
    pricing_used: PRICING.cognito
  }
}

// ============================================================================
// ARCHITECTURE-SPECIFIC PRICING COLLECTION
// ============================================================================

async function collectFaaSPricing (config, projectRoot, awsRegion, startTime, endTime) {
  console.log('\nCollecting FaaS (Lambda + API Gateway) pricing metrics...')

  // Get Lambda infrastructure outputs
  const lambdaInfraDir = path.join(projectRoot, 'infrastructure', 'aws')
  const lambdaOutputs = getTerraformOutputs(lambdaInfraDir)

  // Get API Gateway outputs
  const endpointDir = path.join(projectRoot, 'infrastructure', 'aws', 'endpoint')
  const endpointOutputs = getTerraformOutputs(endpointDir)

  if (!lambdaOutputs) {
    console.log('Could not get Lambda Terraform outputs')
    return null
  }

  const functionNames = lambdaOutputs.lambda_function_names || {}
  const memoryMb = lambdaOutputs.lambda_memory_size || config.memory || 512
  const apiGatewayId = endpointOutputs?.api_gateway_id

  console.log(`  Found ${Object.keys(functionNames).length} Lambda functions`)
  console.log(`  Memory: ${memoryMb} MB`)
  if (apiGatewayId) {
    console.log(`  API Gateway ID: ${apiGatewayId}`)
  }

  const cloudwatch = new CloudWatchClient({ region: awsRegion })
  const startDate = new Date(startTime)
  const endDate = new Date(endTime)
  const period = 60 // 1-minute granularity

  const metricQueries = []
  let queryId = 0

  // Lambda metrics per function
  for (const [shortName, fullName] of Object.entries(functionNames)) {
    // Invocations
    metricQueries.push({
      Id: `lambda_invocations_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/Lambda',
          MetricName: 'Invocations',
          Dimensions: [{ Name: 'FunctionName', Value: fullName }]
        },
        Period: period,
        Stat: 'Sum'
      },
      Label: `Lambda Invocations - ${shortName}`
    })

    // Duration (milliseconds)
    metricQueries.push({
      Id: `lambda_duration_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/Lambda',
          MetricName: 'Duration',
          Dimensions: [{ Name: 'FunctionName', Value: fullName }]
        },
        Period: period,
        Stat: 'Sum' // Sum of all durations in ms
      },
      Label: `Lambda Duration - ${shortName}`
    })

    // Concurrent executions (for capacity analysis)
    metricQueries.push({
      Id: `lambda_concurrent_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/Lambda',
          MetricName: 'ConcurrentExecutions',
          Dimensions: [{ Name: 'FunctionName', Value: fullName }]
        },
        Period: period,
        Stat: 'Maximum'
      },
      Label: `Lambda Concurrent - ${shortName}`
    })
  }

  // API Gateway HTTP API metrics (if available)
  if (apiGatewayId) {
    metricQueries.push({
      Id: `apigw_count_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/ApiGateway',
          MetricName: 'Count',
          Dimensions: [{ Name: 'ApiId', Value: apiGatewayId }]
        },
        Period: period,
        Stat: 'Sum'
      },
      Label: 'API Gateway Request Count'
    })
  }

  // Fetch metrics
  console.log(`\nFetching ${metricQueries.length} metric series...`)

  try {
    const response = await cloudwatch.send(new GetMetricDataCommand({
      MetricDataQueries: metricQueries,
      StartTime: startDate,
      EndTime: endDate
    }))

    // Process results
    const metrics = processMetricResults(response.MetricDataResults)

    // Calculate Lambda costs
    const lambdaCost = calculateLambdaCost(metrics, memoryMb)

    // Calculate API Gateway costs
    const apiGatewayCost = calculateApiGatewayCost(metrics)

    console.log(`  Lambda invocations: ${lambdaCost.total_invocations}`)
    console.log(`  Lambda GB-seconds: ${lambdaCost.gb_seconds.toFixed(2)}`)
    console.log(`  API Gateway requests: ${apiGatewayCost.total_requests}`)

    return {
      meta: {
        architecture: 'faas',
        region: awsRegion,
        memory_mb: memoryMb,
        start_time: startDate.toISOString(),
        end_time: endDate.toISOString(),
        duration_minutes: Math.ceil((endTime - startTime) / 60000),
        collected_at: new Date().toISOString()
      },
      resources: {
        lambda: lambdaCost,
        api_gateway: apiGatewayCost
      },
      raw_metrics: metrics
    }
  } catch (error) {
    console.error(`Failed to collect FaaS pricing metrics: ${error.message}`)
    return null
  }
}

async function collectMonolithPricing (config, projectRoot, awsRegion, startTime, endTime) {
  console.log('\nCollecting Monolith (ECS Fargate + ALB) pricing metrics...')

  const infraDir = path.join(projectRoot, 'infrastructure', 'monolith', 'aws')
  const outputs = getTerraformOutputs(infraDir)

  if (!outputs) {
    console.log('Could not get Terraform outputs for Monolith architecture')
    return null
  }

  const clusterName = outputs.cluster_name
  const serviceName = outputs.service_name
  const albArnSuffix = outputs.alb_arn_suffix

  console.log(`  Cluster: ${clusterName}`)
  console.log(`  Service: ${serviceName}`)
  console.log(`  ALB: ${albArnSuffix}`)

  const cloudwatch = new CloudWatchClient({ region: awsRegion })
  const startDate = new Date(startTime)
  const endDate = new Date(endTime)
  const durationHours = (endTime - startTime) / 3600000
  const period = 60

  // Default task configuration (from variables.tf)
  const taskCpu = 256
  const taskMemory = 512

  const metricQueries = []
  let queryId = 0

  // ECS Service metrics
  metricQueries.push({
    Id: `ecs_running_tasks_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'ECS/ContainerInsights',
        MetricName: 'RunningTaskCount',
        Dimensions: [
          { Name: 'ClusterName', Value: clusterName },
          { Name: 'ServiceName', Value: serviceName }
        ]
      },
      Period: period,
      Stat: 'Average'
    },
    Label: 'ECS Running Tasks'
  })

  // ALB metrics
  metricQueries.push({
    Id: `alb_new_connections_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'NewConnectionCount',
        Dimensions: [{ Name: 'LoadBalancer', Value: albArnSuffix }]
      },
      Period: period,
      Stat: 'Sum'
    },
    Label: 'ALB New Connections'
  })

  metricQueries.push({
    Id: `alb_active_connections_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'ActiveConnectionCount',
        Dimensions: [{ Name: 'LoadBalancer', Value: albArnSuffix }]
      },
      Period: period,
      Stat: 'Average'
    },
    Label: 'ALB Active Connections'
  })

  metricQueries.push({
    Id: `alb_processed_bytes_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'ProcessedBytes',
        Dimensions: [{ Name: 'LoadBalancer', Value: albArnSuffix }]
      },
      Period: period,
      Stat: 'Sum'
    },
    Label: 'ALB Processed Bytes'
  })

  metricQueries.push({
    Id: `alb_request_count_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'RequestCount',
        Dimensions: [{ Name: 'LoadBalancer', Value: albArnSuffix }]
      },
      Period: period,
      Stat: 'Sum'
    },
    Label: 'ALB Request Count'
  })

  try {
    const response = await cloudwatch.send(new GetMetricDataCommand({
      MetricDataQueries: metricQueries,
      StartTime: startDate,
      EndTime: endDate
    }))

    const metrics = processMetricResults(response.MetricDataResults)

    // Calculate Fargate cost
    const fargateCost = calculateFargateCost(metrics, taskCpu, taskMemory, durationHours)

    // Calculate ALB cost
    const albCost = calculateAlbCost(metrics, durationHours)

    console.log(`  Avg running tasks: ${fargateCost.avg_running_tasks.toFixed(2)}`)
    console.log(`  Duration: ${durationHours.toFixed(2)} hours`)

    return {
      meta: {
        architecture: 'monolith',
        region: awsRegion,
        start_time: startDate.toISOString(),
        end_time: endDate.toISOString(),
        duration_hours: durationHours,
        collected_at: new Date().toISOString()
      },
      resources: {
        fargate: fargateCost,
        alb: albCost
      },
      raw_metrics: metrics
    }
  } catch (error) {
    console.error(`Failed to collect Monolith pricing metrics: ${error.message}`)
    return null
  }
}

async function collectMicroservicesPricing (config, projectRoot, awsRegion, startTime, endTime) {
  console.log('\nCollecting Microservices (ECS Fargate + ALB) pricing metrics...')

  const infraDir = path.join(projectRoot, 'infrastructure', 'microservices', 'aws')
  const outputs = getTerraformOutputs(infraDir)

  if (!outputs) {
    console.log('Could not get Terraform outputs for Microservices architecture')
    return null
  }

  const clusterName = outputs.cluster_name
  const serviceNames = outputs.service_names || {}
  const albArnSuffix = outputs.alb_arn_suffix

  console.log(`  Cluster: ${clusterName}`)
  console.log(`  Services: ${Object.keys(serviceNames).join(', ')}`)
  console.log(`  ALB: ${albArnSuffix}`)

  // Default service configurations (from main.tf)
  const defaultTaskCpu = 256
  const defaultTaskMemory = 512

  const cloudwatch = new CloudWatchClient({ region: awsRegion })
  const startDate = new Date(startTime)
  const endDate = new Date(endTime)
  const durationHours = (endTime - startTime) / 3600000
  const period = 60

  const metricQueries = []
  let queryId = 0

  // ECS metrics per service
  for (const [shortName, fullName] of Object.entries(serviceNames)) {
    metricQueries.push({
      Id: `ecs_tasks_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'ECS/ContainerInsights',
          MetricName: 'RunningTaskCount',
          Dimensions: [
            { Name: 'ClusterName', Value: clusterName },
            { Name: 'ServiceName', Value: fullName }
          ]
        },
        Period: period,
        Stat: 'Average'
      },
      Label: `ECS Tasks - ${shortName}`
    })
  }

  // ALB metrics
  metricQueries.push({
    Id: `alb_new_connections_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'NewConnectionCount',
        Dimensions: [{ Name: 'LoadBalancer', Value: albArnSuffix }]
      },
      Period: period,
      Stat: 'Sum'
    },
    Label: 'ALB New Connections'
  })

  metricQueries.push({
    Id: `alb_active_connections_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'ActiveConnectionCount',
        Dimensions: [{ Name: 'LoadBalancer', Value: albArnSuffix }]
      },
      Period: period,
      Stat: 'Average'
    },
    Label: 'ALB Active Connections'
  })

  metricQueries.push({
    Id: `alb_processed_bytes_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'ProcessedBytes',
        Dimensions: [{ Name: 'LoadBalancer', Value: albArnSuffix }]
      },
      Period: period,
      Stat: 'Sum'
    },
    Label: 'ALB Processed Bytes'
  })

  metricQueries.push({
    Id: `alb_request_count_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'RequestCount',
        Dimensions: [{ Name: 'LoadBalancer', Value: albArnSuffix }]
      },
      Period: period,
      Stat: 'Sum'
    },
    Label: 'ALB Request Count'
  })

  try {
    const response = await cloudwatch.send(new GetMetricDataCommand({
      MetricDataQueries: metricQueries,
      StartTime: startDate,
      EndTime: endDate
    }))

    const metrics = processMetricResults(response.MetricDataResults)

    // Calculate per-service Fargate costs
    const serviceCosts = {}
    let totalFargateCost = 0

    for (const shortName of Object.keys(serviceNames)) {
      const serviceFargateCost = calculateFargateCost(
        metrics,
        defaultTaskCpu,
        defaultTaskMemory,
        durationHours,
        `ECS Tasks - ${shortName}`
      )
      serviceCosts[shortName] = serviceFargateCost
      totalFargateCost += serviceFargateCost.total_cost
    }

    // Calculate ALB cost
    const albCost = calculateAlbCost(metrics, durationHours)

    console.log(`  Service count: ${Object.keys(serviceNames).length}`)
    console.log(`  Duration: ${durationHours.toFixed(2)} hours`)

    return {
      meta: {
        architecture: 'microservices',
        region: awsRegion,
        start_time: startDate.toISOString(),
        end_time: endDate.toISOString(),
        duration_hours: durationHours,
        service_count: Object.keys(serviceNames).length,
        collected_at: new Date().toISOString()
      },
      resources: {
        fargate: {
          per_service: serviceCosts,
          total_cost: totalFargateCost,
          task_cpu: defaultTaskCpu,
          task_memory_mb: defaultTaskMemory,
          pricing_used: PRICING.fargate
        },
        alb: albCost
      },
      raw_metrics: metrics
    }
  } catch (error) {
    console.error(`Failed to collect Microservices pricing metrics: ${error.message}`)
    return null
  }
}

// ============================================================================
// COMMON COSTS (Redis, Cognito)
// ============================================================================

function addCommonCosts (pricingData, config, projectRoot, awsRegion, startTime, endTime) {
  const durationHours = (endTime - startTime) / 3600000

  // Redis cost (always deployed on t3a.medium)
  const redisCost = {
    instance_type: 't3a.medium',
    duration_hours: durationHours,
    hourly_rate: PRICING.redis.t3aMediumPerHour,
    total_cost: durationHours * PRICING.redis.t3aMediumPerHour,
    pricing_used: PRICING.redis
  }

  // Cognito cost (estimate based on typical benchmark)
  // For benchmarks, we estimate ~100 unique users
  const estimatedMau = 100
  const cognitoCost = calculateCognitoCost(estimatedMau)
  cognitoCost.note = 'Estimated based on typical benchmark user count'

  pricingData.resources.redis = redisCost
  pricingData.resources.cognito = cognitoCost

  return pricingData
}

// ============================================================================
// TOTALS AND SUMMARY
// ============================================================================

function calculateTotals (pricingData) {
  let totalCost = 0
  const breakdown = {}

  for (const [resource, data] of Object.entries(pricingData.resources)) {
    if (data.total_cost !== undefined) {
      totalCost += data.total_cost
      breakdown[resource] = data.total_cost
    } else if (data.cost !== undefined) {
      totalCost += data.cost
      breakdown[resource] = data.cost
    }
  }

  pricingData.summary = {
    total_cost: totalCost,
    breakdown: breakdown,
    currency: 'USD',
    note: 'Costs are estimates based on AWS published pricing for us-east-1'
  }

  return pricingData
}

function printPricingSummary (pricingData) {
  console.log('\n========================================')
  console.log('PRICING SUMMARY')
  console.log('========================================')
  console.log(`Architecture: ${pricingData.meta.architecture}`)

  if (pricingData.meta.duration_minutes) {
    console.log(`Duration: ${pricingData.meta.duration_minutes} minutes`)
  } else if (pricingData.meta.duration_hours) {
    console.log(`Duration: ${pricingData.meta.duration_hours.toFixed(2)} hours`)
  }

  console.log('')
  console.log('Cost Breakdown:')

  for (const [resource, cost] of Object.entries(pricingData.summary.breakdown)) {
    console.log(`  ${resource}: $${cost.toFixed(6)}`)
  }

  console.log('----------------------------------------')
  console.log(`TOTAL: $${pricingData.summary.total_cost.toFixed(6)}`)
  console.log('========================================\n')
}

// ============================================================================
// MAIN COLLECTION FUNCTION
// ============================================================================

async function collectPricingMetrics (config, outputDir, startTime, endTime = Date.now()) {
  logSection('Collecting Pricing Metrics')

  const { architecture, memory } = config
  const projectRoot = path.join(__dirname, '..', '..')
  const awsRegion = process.env.AWS_REGION || process.env.AWS_DEFAULT_REGION || 'us-east-1'

  console.log(`Architecture: ${architecture}`)
  console.log(`Region: ${awsRegion}`)
  console.log(`Time range: ${new Date(startTime).toISOString()} to ${new Date(endTime).toISOString()}`)

  let pricingData = null

  switch (architecture) {
    case 'faas':
      pricingData = await collectFaaSPricing(config, projectRoot, awsRegion, startTime, endTime)
      break
    case 'monolith':
      pricingData = await collectMonolithPricing(config, projectRoot, awsRegion, startTime, endTime)
      break
    case 'microservices':
      pricingData = await collectMicroservicesPricing(config, projectRoot, awsRegion, startTime, endTime)
      break
    default:
      console.log(`Unknown architecture: ${architecture}, skipping pricing collection`)
      return null
  }

  if (!pricingData) {
    console.log('No pricing data collected')
    return null
  }

  // Add common costs (Redis, Cognito)
  pricingData = addCommonCosts(pricingData, config, projectRoot, awsRegion, startTime, endTime)

  // Calculate totals
  pricingData = calculateTotals(pricingData)

  // Save to file
  const pricingDir = path.join(outputDir, 'pricing')
  if (!fs.existsSync(pricingDir)) {
    fs.mkdirSync(pricingDir, { recursive: true })
  }

  const pricingFile = path.join(pricingDir, 'pricing.json')
  fs.writeFileSync(pricingFile, JSON.stringify(pricingData, null, 2))
  console.log(`\n✓ Pricing data saved to: ${pricingFile}`)

  // Generate summary
  printPricingSummary(pricingData)

  return pricingData
}

module.exports = {
  collectPricingMetrics,
  PRICING
}