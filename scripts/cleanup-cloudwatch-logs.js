#!/usr/bin/env node
/**
 * Cleanup orphaned CloudWatch log groups from previous experiments
 * Usage: node scripts/cleanup-cloudwatch-logs.js [--dry-run] [--prefix <prefix>]
 */

const {
  CloudWatchLogsClient,
  DescribeLogGroupsCommand,
  DeleteLogGroupCommand
} = require('@aws-sdk/client-cloudwatch-logs')

async function cleanupOrphanedLogGroups(dryRun = false, prefix = '/aws/lambda/faas_') {
  const awsRegion = process.env.AWS_REGION || process.env.AWS_DEFAULT_REGION || 'us-east-1'
  const logsClient = new CloudWatchLogsClient({ region: awsRegion })

  console.log(`Searching for orphaned log groups with prefix: ${prefix}`)
  console.log(`AWS Region: ${awsRegion}`)
  console.log(`Mode: ${dryRun ? 'DRY RUN (no deletions)' : 'LIVE (will delete)'}`)
  console.log('')

  // Find all log groups matching prefix
  const logGroups = []
  let nextToken = null

  do {
    const describeCommand = new DescribeLogGroupsCommand({
      logGroupNamePrefix: prefix,
      nextToken
    })
    const response = await logsClient.send(describeCommand)

    for (const group of response.logGroups || []) {
      logGroups.push({
        name: group.logGroupName,
        createdAt: new Date(group.creationTime),
        storedBytes: group.storedBytes || 0
      })
    }
    nextToken = response.nextToken
  } while (nextToken)

  if (logGroups.length === 0) {
    console.log('No orphaned log groups found.')
    return { found: 0, deleted: 0, failed: 0 }
  }

  // Sort by creation time (oldest first)
  logGroups.sort((a, b) => a.createdAt - b.createdAt)

  console.log(`Found ${logGroups.length} log groups:\n`)

  for (const group of logGroups) {
    const sizeKB = (group.storedBytes / 1024).toFixed(1)
    console.log(`  ${group.name}`)
    console.log(`    Created: ${group.createdAt.toISOString()}, Size: ${sizeKB} KB`)
  }

  if (dryRun) {
    console.log(`\nDry run - no log groups deleted.`)
    console.log(`Run without --dry-run to delete these log groups.`)
    return { found: logGroups.length, deleted: 0, failed: 0 }
  }

  console.log(`\nDeleting ${logGroups.length} log groups...`)

  let deleted = 0
  let failed = 0

  for (const group of logGroups) {
    try {
      const deleteCommand = new DeleteLogGroupCommand({ logGroupName: group.name })
      await logsClient.send(deleteCommand)
      deleted++
      console.log(`  Deleted: ${group.name}`)
    } catch (error) {
      if (error.name !== 'ResourceNotFoundException') {
        console.log(`  Failed: ${group.name} - ${error.message}`)
        failed++
      } else {
        deleted++ // Already gone
      }
    }
  }

  console.log(`\nCleanup complete: ${deleted} deleted, ${failed} failed`)
  return { found: logGroups.length, deleted, failed }
}

// Parse command line arguments
const args = process.argv.slice(2)
const dryRun = args.includes('--dry-run')
const prefixIndex = args.indexOf('--prefix')
const prefix = prefixIndex !== -1 && args[prefixIndex + 1] ? args[prefixIndex + 1] : '/aws/lambda/faas_'

cleanupOrphanedLogGroups(dryRun, prefix)
  .then(result => {
    process.exit(result.failed > 0 ? 1 : 0)
  })
  .catch(error => {
    console.error('Error:', error.message)
    process.exit(1)
  })
