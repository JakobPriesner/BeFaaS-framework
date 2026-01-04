const fs = require('fs')
const path = require('path')
const { execSync } = require('child_process')
const {
  CloudWatchClient,
  GetMetricDataCommand
} = require('@aws-sdk/client-cloudwatch')
const { logSection } = require('./utils')

/**
 * Get Terraform outputs from an infrastructure directory
 * @param {string} infraDir - Path to infrastructure directory
 * @returns {Object} Terraform outputs
 */
function getTerraformOutputs (infraDir) {
  try {
    const output = execSync('terraform output -json', {
      cwd: infraDir,
      encoding: 'utf8'
    })
    const outputs = JSON.parse(output)
    // Unwrap the value from each output
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

/**
 * Collect CloudWatch metrics for ECS/ALB (monolith/microservices) or Lambda (FaaS)
 * @param {Object} config - Configuration object with architecture, experiment, etc.
 * @param {string} outputDir - Directory to save metrics
 * @param {number} startTime - Start timestamp in milliseconds
 * @param {number} endTime - End timestamp in milliseconds (defaults to now)
 */
async function collectCloudWatchMetrics (config, outputDir, startTime, endTime = Date.now()) {
  logSection('Collecting CloudWatch Metrics')

  const { architecture } = config
  const projectRoot = path.join(__dirname, '..', '..')

  // Route to architecture-specific metrics collection
  if (architecture === 'faas') {
    return await collectFaaSCloudWatchMetrics(config, outputDir, startTime, endTime, projectRoot)
  } else if (architecture === 'monolith' || architecture === 'microservices') {
    return await collectECSCloudWatchMetrics(config, outputDir, startTime, endTime, projectRoot)
  } else {
    console.log(`Unknown architecture: ${architecture}`)
    return null
  }
}

/**
 * Collect CloudWatch metrics for FaaS architecture (Lambda only - essential metrics)
 * Collects: Duration, Concurrent Executions, Throttles, Errors, Invocations per function
 * Note: Latency/throughput captured by Artillery, so skipping API Gateway metrics
 */
async function collectFaaSCloudWatchMetrics (config, outputDir, startTime, endTime, projectRoot) {
  const { architecture } = config

  // Get infrastructure directory for FaaS
  const infraDir = path.join(projectRoot, 'infrastructure', 'aws')
  if (!fs.existsSync(path.join(infraDir, 'terraform.tfstate'))) {
    console.log('No Terraform state found for FaaS infrastructure, skipping CloudWatch metrics')
    return null
  }

  // Get Terraform outputs
  const outputs = getTerraformOutputs(infraDir)
  if (!outputs) {
    return null
  }

  // Validate required outputs
  if (!outputs.lambda_function_names || Object.keys(outputs.lambda_function_names).length === 0) {
    console.log('⚠️ No Lambda functions found in Terraform outputs')
    return null
  }

  const lambdaFunctionNames = Object.values(outputs.lambda_function_names)
  const lambdaMemorySize = outputs.lambda_memory_size || 'unknown'

  console.log('Retrieved Terraform outputs:')
  console.log(`  Lambda Functions: ${lambdaFunctionNames.length}`)
  console.log(`  Lambda Memory: ${lambdaMemorySize} MB`)

  // Get AWS region
  const awsRegion = process.env.AWS_REGION || process.env.AWS_DEFAULT_REGION || 'us-east-1'
  console.log(`  Region: ${awsRegion}`)

  // Initialize CloudWatch client
  const cloudwatch = new CloudWatchClient({ region: awsRegion })

  // Calculate time range
  const startDate = new Date(startTime)
  const endDate = new Date(endTime)
  const durationMinutes = Math.ceil((endTime - startTime) / 60000)

  // Use 1-minute period for granular data
  const period = 60

  console.log(`\nTime range: ${startDate.toISOString()} to ${endDate.toISOString()}`)
  console.log(`Duration: ${durationMinutes} minutes`)

  // Build metric queries - essential Lambda metrics only
  const metricQueries = []
  let queryId = 0

  for (const functionName of lambdaFunctionNames) {
    // Extract short name for labels (remove project prefix)
    const shortName = functionName.includes('-')
      ? functionName.split('-').slice(1).join('-')
      : functionName

    // Invocations
    metricQueries.push({
      Id: `lambda_inv_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/Lambda',
          MetricName: 'Invocations',
          Dimensions: [{ Name: 'FunctionName', Value: functionName }]
        },
        Period: period,
        Stat: 'Sum'
      },
      Label: `Lambda Invocations - ${shortName}`
    })

    // Duration (avg, p95, p99)
    metricQueries.push({
      Id: `lambda_dur_avg_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/Lambda',
          MetricName: 'Duration',
          Dimensions: [{ Name: 'FunctionName', Value: functionName }]
        },
        Period: period,
        Stat: 'Average'
      },
      Label: `Lambda Duration (avg) - ${shortName}`
    })

    metricQueries.push({
      Id: `lambda_dur_p95_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/Lambda',
          MetricName: 'Duration',
          Dimensions: [{ Name: 'FunctionName', Value: functionName }]
        },
        Period: period,
        Stat: 'p95'
      },
      Label: `Lambda Duration (p95) - ${shortName}`
    })

    metricQueries.push({
      Id: `lambda_dur_p99_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/Lambda',
          MetricName: 'Duration',
          Dimensions: [{ Name: 'FunctionName', Value: functionName }]
        },
        Period: period,
        Stat: 'p99'
      },
      Label: `Lambda Duration (p99) - ${shortName}`
    })

    // Errors
    metricQueries.push({
      Id: `lambda_err_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/Lambda',
          MetricName: 'Errors',
          Dimensions: [{ Name: 'FunctionName', Value: functionName }]
        },
        Period: period,
        Stat: 'Sum'
      },
      Label: `Lambda Errors - ${shortName}`
    })

    // Throttles
    metricQueries.push({
      Id: `lambda_thr_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/Lambda',
          MetricName: 'Throttles',
          Dimensions: [{ Name: 'FunctionName', Value: functionName }]
        },
        Period: period,
        Stat: 'Sum'
      },
      Label: `Lambda Throttles - ${shortName}`
    })

    // Concurrent Executions (max, avg)
    metricQueries.push({
      Id: `lambda_conc_max_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/Lambda',
          MetricName: 'ConcurrentExecutions',
          Dimensions: [{ Name: 'FunctionName', Value: functionName }]
        },
        Period: period,
        Stat: 'Maximum'
      },
      Label: `Lambda Concurrent Executions (max) - ${shortName}`
    })

    metricQueries.push({
      Id: `lambda_conc_avg_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/Lambda',
          MetricName: 'ConcurrentExecutions',
          Dimensions: [{ Name: 'FunctionName', Value: functionName }]
        },
        Period: period,
        Stat: 'Average'
      },
      Label: `Lambda Concurrent Executions (avg) - ${shortName}`
    })
  }

  // Fetch metrics (CloudWatch allows max 500 metrics per request)
  console.log(`\nFetching ${metricQueries.length} metric series...`)

  try {
    // Split queries into batches of 500 (CloudWatch limit)
    const batchSize = 500
    const allResults = []

    for (let i = 0; i < metricQueries.length; i += batchSize) {
      const batch = metricQueries.slice(i, i + batchSize)
      const command = new GetMetricDataCommand({
        MetricDataQueries: batch,
        StartTime: startDate,
        EndTime: endDate
      })

      const response = await cloudwatch.send(command)
      allResults.push(...response.MetricDataResults)

      if (metricQueries.length > batchSize) {
        console.log(`  Fetched batch ${Math.floor(i / batchSize) + 1}/${Math.ceil(metricQueries.length / batchSize)}`)
      }
    }

    // Process results
    const metricsData = {
      meta: {
        architecture,
        lambda_functions: lambdaFunctionNames,
        lambda_memory_size_mb: lambdaMemorySize,
        region: awsRegion,
        start_time: startDate.toISOString(),
        end_time: endDate.toISOString(),
        period_seconds: period,
        collected_at: new Date().toISOString()
      },
      metrics: {}
    }

    for (const result of allResults) {
      const metricName = result.Label
      const timestamps = result.Timestamps || []
      const values = result.Values || []

      // Combine timestamps and values into data points
      const dataPoints = timestamps.map((ts, i) => ({
        timestamp: ts.toISOString(),
        value: values[i]
      }))

      // Sort by timestamp ascending
      dataPoints.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))

      metricsData.metrics[metricName] = {
        id: result.Id,
        status: result.StatusCode,
        data_points: dataPoints,
        summary: dataPoints.length > 0
          ? {
              count: dataPoints.length,
              min: Math.min(...values),
              max: Math.max(...values),
              avg: values.reduce((a, b) => a + b, 0) / values.length
            }
          : null
      }

      console.log(`  ${metricName}: ${dataPoints.length} data points`)
    }

    // Save metrics to file
    const metricsDir = path.join(outputDir, 'cloudwatch')
    if (!fs.existsSync(metricsDir)) {
      fs.mkdirSync(metricsDir, { recursive: true })
    }

    const metricsFile = path.join(metricsDir, 'metrics.json')
    fs.writeFileSync(metricsFile, JSON.stringify(metricsData, null, 2))
    console.log(`\n✓ FaaS CloudWatch metrics saved to: ${metricsFile}`)

    // Save Lambda metrics as CSV
    await saveFaaSMetricsAsCsv(metricsData, metricsDir)

    return metricsData
  } catch (error) {
    console.error(`✗ FaaS metrics collection failed: ${error.message}`)
    return null
  }
}

/**
 * Save FaaS metrics data as CSV files
 */
async function saveFaaSMetricsAsCsv (metricsData, metricsDir) {
  const lambdaMetrics = {}

  for (const [name, metric] of Object.entries(metricsData.metrics)) {
    if (name.startsWith('Lambda')) {
      lambdaMetrics[name] = metric
    }
  }

  if (Object.keys(lambdaMetrics).length > 0) {
    const csvFile = path.join(metricsDir, 'lambda_metrics.csv')
    const csv = generateCsv(lambdaMetrics)
    fs.writeFileSync(csvFile, csv)
    console.log(`✓ Lambda metrics CSV saved to: ${csvFile}`)
  }
}

/**
 * Collect CloudWatch metrics for ECS-based architectures (monolith/microservices)
 */
async function collectECSCloudWatchMetrics (config, outputDir, startTime, endTime, projectRoot) {
  const { architecture } = config

  // Get infrastructure directory
  const infraDir = path.join(projectRoot, 'infrastructure', architecture, 'aws')
  if (!fs.existsSync(path.join(infraDir, 'terraform.tfstate'))) {
    console.log('No Terraform state found, skipping CloudWatch metrics')
    return null
  }

  // Get Terraform outputs
  const outputs = getTerraformOutputs(infraDir)
  if (!outputs) {
    return null
  }

  console.log('Retrieved Terraform outputs:')
  console.log(`  Cluster: ${outputs.cluster_name}`)
  console.log(`  ALB ARN Suffix: ${outputs.alb_arn_suffix}`)

  // Get AWS region
  const awsRegion = process.env.AWS_REGION || process.env.AWS_DEFAULT_REGION || 'us-east-1'
  console.log(`  Region: ${awsRegion}`)

  // Initialize CloudWatch client
  const cloudwatch = new CloudWatchClient({ region: awsRegion })

  // Calculate time range
  const startDate = new Date(startTime)
  const endDate = new Date(endTime)
  const durationMinutes = Math.ceil((endTime - startTime) / 60000)

  // Use 1-minute period for granular data
  const period = 60

  console.log(`\nTime range: ${startDate.toISOString()} to ${endDate.toISOString()}`)
  console.log(`Duration: ${durationMinutes} minutes`)

  // Build metric queries
  const metricQueries = []
  let queryId = 0

  // ECS metrics
  const clusterName = outputs.cluster_name
  const serviceNames = architecture === 'monolith'
    ? [outputs.service_name]
    : Object.values(outputs.service_names || {})

  for (const serviceName of serviceNames) {
    // CPU Utilization
    metricQueries.push({
      Id: `ecs_cpu_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/ECS',
          MetricName: 'CPUUtilization',
          Dimensions: [
            { Name: 'ClusterName', Value: clusterName },
            { Name: 'ServiceName', Value: serviceName }
          ]
        },
        Period: period,
        Stat: 'Average'
      },
      Label: `ECS CPU - ${serviceName}`
    })

    // Memory Utilization
    metricQueries.push({
      Id: `ecs_mem_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/ECS',
          MetricName: 'MemoryUtilization',
          Dimensions: [
            { Name: 'ClusterName', Value: clusterName },
            { Name: 'ServiceName', Value: serviceName }
          ]
        },
        Period: period,
        Stat: 'Average'
      },
      Label: `ECS Memory - ${serviceName}`
    })
  }

  // ALB metrics
  const albArnSuffix = outputs.alb_arn_suffix
  const targetGroupArnSuffix = outputs.target_group_arn_suffix

  // Request Count
  metricQueries.push({
    Id: `alb_requests_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'RequestCount',
        Dimensions: [
          { Name: 'LoadBalancer', Value: albArnSuffix }
        ]
      },
      Period: period,
      Stat: 'Sum'
    },
    Label: 'ALB Request Count'
  })

  // Target Response Time
  metricQueries.push({
    Id: `alb_response_time_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'TargetResponseTime',
        Dimensions: [
          { Name: 'LoadBalancer', Value: albArnSuffix }
        ]
      },
      Period: period,
      Stat: 'Average'
    },
    Label: 'ALB Target Response Time (avg)'
  })

  // Target Response Time p95
  metricQueries.push({
    Id: `alb_response_time_p95_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'TargetResponseTime',
        Dimensions: [
          { Name: 'LoadBalancer', Value: albArnSuffix }
        ]
      },
      Period: period,
      Stat: 'p95'
    },
    Label: 'ALB Target Response Time (p95)'
  })

  // HTTP 2XX Count
  metricQueries.push({
    Id: `alb_2xx_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'HTTPCode_Target_2XX_Count',
        Dimensions: [
          { Name: 'LoadBalancer', Value: albArnSuffix }
        ]
      },
      Period: period,
      Stat: 'Sum'
    },
    Label: 'ALB HTTP 2XX Count'
  })

  // HTTP 4XX Count
  metricQueries.push({
    Id: `alb_4xx_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'HTTPCode_Target_4XX_Count',
        Dimensions: [
          { Name: 'LoadBalancer', Value: albArnSuffix }
        ]
      },
      Period: period,
      Stat: 'Sum'
    },
    Label: 'ALB HTTP 4XX Count'
  })

  // HTTP 5XX Count
  metricQueries.push({
    Id: `alb_5xx_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'HTTPCode_Target_5XX_Count',
        Dimensions: [
          { Name: 'LoadBalancer', Value: albArnSuffix }
        ]
      },
      Period: period,
      Stat: 'Sum'
    },
    Label: 'ALB HTTP 5XX Count'
  })

  // Active Connection Count
  metricQueries.push({
    Id: `alb_connections_${queryId++}`,
    MetricStat: {
      Metric: {
        Namespace: 'AWS/ApplicationELB',
        MetricName: 'ActiveConnectionCount',
        Dimensions: [
          { Name: 'LoadBalancer', Value: albArnSuffix }
        ]
      },
      Period: period,
      Stat: 'Sum'
    },
    Label: 'ALB Active Connections'
  })

  // Target Group - Healthy Host Count
  if (targetGroupArnSuffix) {
    metricQueries.push({
      Id: `tg_healthy_${queryId++}`,
      MetricStat: {
        Metric: {
          Namespace: 'AWS/ApplicationELB',
          MetricName: 'HealthyHostCount',
          Dimensions: [
            { Name: 'TargetGroup', Value: targetGroupArnSuffix },
            { Name: 'LoadBalancer', Value: albArnSuffix }
          ]
        },
        Period: period,
        Stat: 'Average'
      },
      Label: 'Target Group Healthy Hosts'
    })
  }

  // Fetch metrics (CloudWatch allows max 500 metrics per request)
  console.log(`\nFetching ${metricQueries.length} metric series...`)

  try {
    const command = new GetMetricDataCommand({
      MetricDataQueries: metricQueries,
      StartTime: startDate,
      EndTime: endDate
    })

    const response = await cloudwatch.send(command)

    // Process results
    const metricsData = {
      meta: {
        architecture,
        cluster_name: clusterName,
        service_names: serviceNames,
        alb_arn_suffix: albArnSuffix,
        target_group_arn_suffix: targetGroupArnSuffix,
        region: awsRegion,
        start_time: startDate.toISOString(),
        end_time: endDate.toISOString(),
        period_seconds: period,
        collected_at: new Date().toISOString()
      },
      metrics: {}
    }

    for (const result of response.MetricDataResults) {
      const metricName = result.Label
      const timestamps = result.Timestamps || []
      const values = result.Values || []

      // Combine timestamps and values into data points
      const dataPoints = timestamps.map((ts, i) => ({
        timestamp: ts.toISOString(),
        value: values[i]
      }))

      // Sort by timestamp ascending
      dataPoints.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))

      metricsData.metrics[metricName] = {
        id: result.Id,
        status: result.StatusCode,
        data_points: dataPoints,
        summary: dataPoints.length > 0
          ? {
              count: dataPoints.length,
              min: Math.min(...values),
              max: Math.max(...values),
              avg: values.reduce((a, b) => a + b, 0) / values.length
            }
          : null
      }

      console.log(`  ${metricName}: ${dataPoints.length} data points`)
    }

    // Save metrics to file
    const metricsDir = path.join(outputDir, 'cloudwatch')
    if (!fs.existsSync(metricsDir)) {
      fs.mkdirSync(metricsDir, { recursive: true })
    }

    const metricsFile = path.join(metricsDir, 'metrics.json')
    fs.writeFileSync(metricsFile, JSON.stringify(metricsData, null, 2))
    console.log(`\n✓ CloudWatch metrics saved to: ${metricsFile}`)

    // Also save a CSV for easy graphing
    await saveMetricsAsCsv(metricsData, metricsDir)

    return metricsData
  } catch (error) {
    console.error(`✗ Failed to collect CloudWatch metrics: ${error.message}`)
    return null
  }
}

/**
 * Save metrics data as CSV files for easy graphing
 * @param {Object} metricsData - Metrics data object
 * @param {string} metricsDir - Directory to save CSV files
 */
async function saveMetricsAsCsv (metricsData, metricsDir) {
  // Create separate CSVs for ECS and ALB metrics
  const ecsMetrics = {}
  const albMetrics = {}

  for (const [name, metric] of Object.entries(metricsData.metrics)) {
    if (name.startsWith('ECS')) {
      ecsMetrics[name] = metric
    } else {
      albMetrics[name] = metric
    }
  }

  // Save ECS metrics CSV
  if (Object.keys(ecsMetrics).length > 0) {
    const ecsCsvFile = path.join(metricsDir, 'ecs_metrics.csv')
    const ecsCsv = generateCsv(ecsMetrics)
    fs.writeFileSync(ecsCsvFile, ecsCsv)
    console.log(`✓ ECS metrics CSV saved to: ${ecsCsvFile}`)
  }

  // Save ALB metrics CSV
  if (Object.keys(albMetrics).length > 0) {
    const albCsvFile = path.join(metricsDir, 'alb_metrics.csv')
    const albCsv = generateCsv(albMetrics)
    fs.writeFileSync(albCsvFile, albCsv)
    console.log(`✓ ALB metrics CSV saved to: ${albCsvFile}`)
  }
}

/**
 * Generate CSV from metrics object
 * @param {Object} metrics - Metrics object
 * @returns {string} CSV content
 */
function generateCsv (metrics) {
  // Get all unique timestamps across all metrics
  const allTimestamps = new Set()
  for (const metric of Object.values(metrics)) {
    for (const dp of metric.data_points) {
      allTimestamps.add(dp.timestamp)
    }
  }

  const sortedTimestamps = Array.from(allTimestamps).sort()
  const metricNames = Object.keys(metrics)

  // Build header
  const header = ['timestamp', ...metricNames].join(',')

  // Build rows
  const rows = sortedTimestamps.map(ts => {
    const values = metricNames.map(name => {
      const dp = metrics[name].data_points.find(d => d.timestamp === ts)
      return dp ? dp.value : ''
    })
    return [ts, ...values].join(',')
  })

  return [header, ...rows].join('\n')
}

module.exports = {
  collectCloudWatchMetrics
}
