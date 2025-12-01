const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');

// S3 bucket configuration for results upload
const S3_BUCKET_NAME = 'jakobs-benchmark-results';
const S3_REGION = 'us-east-1';

function logSection(title) {
  console.log('\n' + '='.repeat(60));
  console.log(`  ${title}`);
  console.log('='.repeat(60) + '\n');
}

async function checkHealth(endpoints, maxRetries = 10, retryDelay = 3000) {
  if (!endpoints || endpoints.length === 0) {
    console.log('No health check endpoints configured, skipping health check');
    return true;
  }

  logSection('Health Check');
  console.log(`Checking ${endpoints.length} endpoint(s)...`);

  async function checkEndpoint(url) {
    return new Promise((resolve) => {
      const client = url.startsWith('https') ? https : http;
      const req = client.get(url, { timeout: 5000 }, (res) => {
        resolve(res.statusCode >= 200 && res.statusCode < 300);
      });

      req.on('error', () => resolve(false));
      req.on('timeout', () => {
        req.destroy();
        resolve(false);
      });
    });
  }

  const results = {};
  for (const endpoint of endpoints) {
    results[endpoint] = false;
  }

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    console.log(`\nAttempt ${attempt}/${maxRetries}`);

    for (const endpoint of endpoints) {
      if (results[endpoint]) {
        console.log(`  ✓ ${endpoint} (already healthy)`);
        continue;
      }

      const isHealthy = await checkEndpoint(endpoint);
      results[endpoint] = isHealthy;

      if (isHealthy) {
        console.log(`  ✓ ${endpoint}`);
      } else {
        console.log(`  ✗ ${endpoint}`);
      }
    }

    // Check if all endpoints are healthy
    const allHealthy = Object.values(results).every(v => v === true);
    if (allHealthy) {
      console.log('\n✓ All services are healthy!');
      return true;
    }

    // Wait before next retry (except on last attempt)
    if (attempt < maxRetries) {
      console.log(`\nWaiting ${retryDelay / 1000}s before next check...`);
      await new Promise(resolve => setTimeout(resolve, retryDelay));
    }
  }

  // Final check
  const unhealthyEndpoints = Object.entries(results)
    .filter(([_, healthy]) => !healthy)
    .map(([endpoint]) => endpoint);

  if (unhealthyEndpoints.length > 0) {
    console.error('\n❌ Some services failed health check:');
    unhealthyEndpoints.forEach(endpoint => console.error(`  - ${endpoint}`));
    return false;
  }

  return true;
}

function cleanupBuildArtifacts(experiment, architecture) {
  logSection('Cleaning up build artifacts');

  const projectRoot = path.join(__dirname, '..', '..');
  const pathsToClean = [
    // Architecture-specific build directory
    path.join(projectRoot, 'experiments', experiment, 'architectures', architecture, '_build'),
    // Shared functions build directory
    path.join(projectRoot, 'experiments', experiment, 'functions', '_build'),
    // Results directory for this architecture
    path.join(projectRoot, 'results', experiment, `${architecture}-*`)
  ];

  for (const cleanPath of pathsToClean) {
    // Handle glob patterns for results directory
    if (cleanPath.includes('*')) {
      const dirPath = path.dirname(cleanPath);
      const pattern = path.basename(cleanPath);
      if (fs.existsSync(dirPath)) {
        const entries = fs.readdirSync(dirPath);
        for (const entry of entries) {
          if (entry.match(new RegExp(pattern.replace('*', '.*')))) {
            const fullPath = path.join(dirPath, entry);
            console.log(`  Removing: ${fullPath}`);
            if (fs.existsSync(fullPath)) {
              fs.rmSync(fullPath, { recursive: true, force: true });
            }
          }
        }
      }
    } else {
      if (fs.existsSync(cleanPath)) {
        console.log(`  Removing: ${cleanPath}`);
        fs.rmSync(cleanPath, { recursive: true, force: true });
      }
    }
  }

  console.log('✓ Cleanup completed');
}

function deleteLocalResults(outputDir) {
  logSection('Deleting Local Results');

  const absoluteOutputDir = path.resolve(outputDir);

  console.log(`Deleting local results from: ${absoluteOutputDir}`);

  try {
    if (fs.existsSync(absoluteOutputDir)) {
      fs.rmSync(absoluteOutputDir, { recursive: true, force: true });
      console.log('✓ Local results deleted successfully');
    } else {
      console.log('⚠ Output directory does not exist, nothing to delete');
    }
  } catch (error) {
    console.error('✗ Failed to delete local results:', error.message);
  }
}

async function uploadResultsToS3(outputDir, experiment, architecture, auth) {
  const { execSync } = require('child_process');

  logSection('Uploading Results to S3');

  const absoluteOutputDir = path.resolve(outputDir);
  const dirName = path.basename(absoluteOutputDir);
  const s3Key = `${experiment}/${dirName}`;

  console.log(`Uploading results from: ${absoluteOutputDir}`);
  console.log(`S3 destination: s3://${S3_BUCKET_NAME}/${s3Key}/`);

  try {
    // Use AWS CLI to sync the results directory to S3
    const syncCommand = `aws s3 sync "${absoluteOutputDir}" "s3://${S3_BUCKET_NAME}/${s3Key}/" --region ${S3_REGION}`;

    execSync(syncCommand, {
      stdio: 'inherit',
      shell: '/bin/bash'
    });

    console.log(`✓ Results uploaded to s3://${S3_BUCKET_NAME}/${s3Key}/`);
    return true;
  } catch (error) {
    console.error('✗ Failed to upload results to S3:', error.message);
    console.log('Note: Ensure AWS CLI is configured and has permissions to write to the S3 bucket');
    return false;
  }
}

function setupLogging(outputDir) {
  const logFile = path.join(outputDir, 'experiment.log');
  const logStream = fs.createWriteStream(logFile, { flags: 'a' });

  // Capture stdout and stderr
  const originalStdoutWrite = process.stdout.write.bind(process.stdout);
  const originalStderrWrite = process.stderr.write.bind(process.stderr);

  process.stdout.write = (chunk, encoding, callback) => {
    logStream.write(chunk, encoding);
    return originalStdoutWrite(chunk, encoding, callback);
  };

  process.stderr.write = (chunk, encoding, callback) => {
    logStream.write(chunk, encoding);
    return originalStderrWrite(chunk, encoding, callback);
  };

  return logFile;
}

module.exports = {
  S3_BUCKET_NAME,
  S3_REGION,
  logSection,
  checkHealth,
  cleanupBuildArtifacts,
  deleteLocalResults,
  uploadResultsToS3,
  setupLogging
};