#!/usr/bin/env node

/**
 * Backfill missing configuration files in experiment result directories.
 *
 * This script scans result directories and creates missing files:
 * - hardware_config.json
 * - benchmark_configuration.json
 * - error_description.md
 * - experiment_start_time.txt
 *
 * Usage:
 *   node scripts/backfill-config-files.js [results_dir]
 *
 * Default results_dir: scripts/results/webservice
 */

const fs = require('fs');
const path = require('path');

// Terraform variable defaults for scaling rules backfill
const SCALING_DEFAULTS = {
  monolith: {
    monolith: {
      cpu_units: 512,
      memory_mb: 1024,
      min_capacity: 2,
      max_capacity: 100,
      scaling_rules: {
        request_count: {
          target_value: 2500,
          scale_in_cooldown_sec: 300,
          scale_out_cooldown_sec: 60
        }
      }
    }
  },
  microservices: {
    'frontend-service': {
      cpu_units: 256, memory_mb: 512, min_capacity: 2, max_capacity: 100,
      scaling_rules: {
        cpu: { target_value: 70, scale_in_cooldown_sec: 180, scale_out_cooldown_sec: 45 },
        request_count: { target_value: 5000, scale_in_cooldown_sec: 180, scale_out_cooldown_sec: 45 }
      }
    },
    'product-service': {
      cpu_units: 256, memory_mb: 512, min_capacity: 1, max_capacity: 100,
      scaling_rules: {
        cpu: { target_value: 70, scale_in_cooldown_sec: 180, scale_out_cooldown_sec: 45 }
      }
    },
    'cart-service': {
      cpu_units: 256, memory_mb: 512, min_capacity: 1, max_capacity: 100,
      scaling_rules: {
        cpu: { target_value: 70, scale_in_cooldown_sec: 180, scale_out_cooldown_sec: 45 }
      }
    },
    'order-service': {
      cpu_units: 256, memory_mb: 512, min_capacity: 1, max_capacity: 100,
      scaling_rules: {
        cpu: { target_value: 70, scale_in_cooldown_sec: 180, scale_out_cooldown_sec: 45 }
      }
    },
    'content-service': {
      cpu_units: 256, memory_mb: 512, min_capacity: 1, max_capacity: 100,
      scaling_rules: {
        cpu: { target_value: 70, scale_in_cooldown_sec: 180, scale_out_cooldown_sec: 45 }
      }
    }
  }
};

/**
 * Parse experiment directory name to extract configuration.
 * Format: {architecture}_{auth}_{memory}MB_[{workload}_]{timestamp}
 * or:     {architecture}_{auth}_{cpu}cpu_{memory}MB_{timestamp}
 */
function parseDirectoryName(dirName) {
  // Pattern for FaaS: faas_none_256MB_minimal_2026-01-09T10-26-01-144Z
  // Pattern for ECS: microservices_none_1024cpu_2048MB_2026-01-15T00-14-08-976Z

  const parts = dirName.split('_');
  if (parts.length < 4) {
    return null;
  }

  const architecture = parts[0];
  const auth = parts[1];

  let ramInMb = null;
  let cpuInVcpu = null;
  let cpuUnits = null;
  let timestamp = null;

  // Find memory and CPU parts
  for (let i = 2; i < parts.length; i++) {
    const part = parts[i];

    if (part.endsWith('MB')) {
      ramInMb = parseInt(part.replace('MB', ''), 10);
    } else if (part.endsWith('cpu')) {
      cpuUnits = parseInt(part.replace('cpu', ''), 10);
      cpuInVcpu = cpuUnits / 1024;
    } else if (part.match(/^\d{4}-\d{2}-\d{2}T/)) {
      // This is the timestamp - collect it and remaining parts
      timestamp = parts.slice(i).join('_');
      break;
    }
  }

  if (!ramInMb || !timestamp) {
    return null;
  }

  return {
    architecture,
    auth,
    ramInMb,
    cpuInVcpu,
    cpuUnits,
    timestamp
  };
}

/**
 * Convert directory timestamp to ISO format.
 * Input: 2026-01-09T10-26-01-144Z
 * Output: 2026-01-09T10:26:01.144Z
 */
function timestampToIso(timestamp) {
  // Replace dashes in time portion with colons
  // Format: YYYY-MM-DDTHH-MM-SS-mmmZ -> YYYY-MM-DDTHH:MM:SS.mmmZ
  const match = timestamp.match(/^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})-(\d{3})Z$/);
  if (match) {
    return `${match[1]}T${match[2]}:${match[3]}:${match[4]}.${match[5]}Z`;
  }
  return timestamp;
}

/**
 * Convert ISO timestamp to milliseconds.
 */
function isoToMs(isoTimestamp) {
  return new Date(isoTimestamp).getTime();
}

/**
 * Backfill missing config files in a directory.
 */
function backfillDirectory(dirPath) {
  const dirName = path.basename(dirPath);
  const config = parseDirectoryName(dirName);

  if (!config) {
    console.log(`  ⚠️  Could not parse directory name: ${dirName}`);
    return { skipped: true };
  }

  const results = {
    hardwareConfig: false,
    benchmarkConfig: false,
    errorDescription: false,
    experimentStartTime: false
  };

  // 1. hardware_config.json
  const hardwareConfigPath = path.join(dirPath, 'hardware_config.json');
  if (!fs.existsSync(hardwareConfigPath)) {
    const hardwareConfig = {
      architecture: config.architecture,
      auth_strategy: config.auth,
      aws_service: config.architecture === 'faas' ? 'lambda' : 'ecs fargate',
      ram_in_mb: config.ramInMb,
      datetime: config.timestamp
    };
    if (config.cpuInVcpu) {
      hardwareConfig.cpu_in_vcpu = config.cpuInVcpu;
    }
    if (config.auth === 'service-integrated-manual') {
      hardwareConfig.password_hash_algorithm = 'argon2id';
      hardwareConfig.jwt_sign_algorithm = 'EdDSA';
    }
    // Add per-service scaling rules for ECS architectures
    if (config.architecture in SCALING_DEFAULTS) {
      const defaults = SCALING_DEFAULTS[config.architecture];
      const services = {};
      for (const [svcName, svcDefaults] of Object.entries(defaults)) {
        services[svcName] = {
          cpu_units: config.cpuUnits || svcDefaults.cpu_units,
          memory_mb: svcName === Object.keys(defaults)[0] ? config.ramInMb : svcDefaults.memory_mb,
          min_capacity: svcDefaults.min_capacity,
          max_capacity: svcDefaults.max_capacity,
          scaling_rules: svcDefaults.scaling_rules
        };
      }
      hardwareConfig.services = services;
    }
    fs.writeFileSync(hardwareConfigPath, JSON.stringify(hardwareConfig, null, 2));
    results.hardwareConfig = true;
    console.log(`  ✓ Created hardware_config.json`);
  } else {
    // Update existing hardware_config.json with per-service scaling rules if missing
    try {
      const existing = JSON.parse(fs.readFileSync(hardwareConfigPath, 'utf8'));
      if (!existing.services && existing.architecture in SCALING_DEFAULTS) {
        const defaults = SCALING_DEFAULTS[existing.architecture];
        const services = {};
        for (const [svcName, svcDefaults] of Object.entries(defaults)) {
          services[svcName] = {
            cpu_units: config.cpuUnits || svcDefaults.cpu_units,
            memory_mb: svcName === Object.keys(defaults)[0] ? (existing.ram_in_mb || config.ramInMb) : svcDefaults.memory_mb,
            min_capacity: svcDefaults.min_capacity,
            max_capacity: svcDefaults.max_capacity,
            scaling_rules: svcDefaults.scaling_rules
          };
        }
        existing.services = services;
        fs.writeFileSync(hardwareConfigPath, JSON.stringify(existing, null, 2));
        results.hardwareConfig = true;
        console.log(`  ✓ Updated hardware_config.json with per-service scaling rules`);
      }
    } catch (e) {
      console.log(`  ⚠️  Could not update hardware_config.json: ${e.message}`);
    }
  }

  // 2. benchmark_configuration.json
  const benchmarkConfigPath = path.join(dirPath, 'benchmark_configuration.json');
  if (!fs.existsSync(benchmarkConfigPath)) {
    const benchmarkConfig = {
      http_timeout_in_seconds: config.architecture === 'faas' ? 10 : 30
    };
    fs.writeFileSync(benchmarkConfigPath, JSON.stringify(benchmarkConfig, null, 2));
    results.benchmarkConfig = true;
    console.log(`  ✓ Created benchmark_configuration.json`);
  }

  // 3. error_description.md
  const errorDescPath = path.join(dirPath, 'error_description.md');
  if (!fs.existsSync(errorDescPath)) {
    fs.writeFileSync(errorDescPath, '');
    results.errorDescription = true;
    console.log(`  ✓ Created error_description.md`);
  }

  // 4. experiment_start_time.txt
  const startTimePath = path.join(dirPath, 'experiment_start_time.txt');
  if (!fs.existsSync(startTimePath)) {
    const isoTime = timestampToIso(config.timestamp);
    const msTime = isoToMs(isoTime);
    if (!isNaN(msTime)) {
      fs.writeFileSync(startTimePath, `${msTime}\n${isoTime}`);
      results.experimentStartTime = true;
      console.log(`  ✓ Created experiment_start_time.txt`);
    } else {
      console.log(`  ⚠️  Could not parse timestamp: ${config.timestamp}`);
    }
  }

  return results;
}

/**
 * Main function.
 */
function main() {
  const args = process.argv.slice(2);
  const resultsDir = args[0] || path.join(__dirname, 'results', 'webservice');

  if (!fs.existsSync(resultsDir)) {
    console.error(`Error: Results directory not found: ${resultsDir}`);
    process.exit(1);
  }

  console.log(`Scanning: ${resultsDir}\n`);

  const dirs = fs.readdirSync(resultsDir)
    .filter(name => {
      const fullPath = path.join(resultsDir, name);
      return fs.statSync(fullPath).isDirectory() && !name.startsWith('.');
    })
    .sort();

  console.log(`Found ${dirs.length} experiment directories\n`);

  let totalCreated = {
    hardwareConfig: 0,
    benchmarkConfig: 0,
    errorDescription: 0,
    experimentStartTime: 0,
    skipped: 0
  };

  for (const dir of dirs) {
    const dirPath = path.join(resultsDir, dir);
    console.log(`Processing: ${dir}`);

    const results = backfillDirectory(dirPath);

    if (results.skipped) {
      totalCreated.skipped++;
    } else {
      if (results.hardwareConfig) totalCreated.hardwareConfig++;
      if (results.benchmarkConfig) totalCreated.benchmarkConfig++;
      if (results.errorDescription) totalCreated.errorDescription++;
      if (results.experimentStartTime) totalCreated.experimentStartTime++;
    }
  }

  console.log('\n=== Summary ===');
  console.log(`  hardware_config.json created: ${totalCreated.hardwareConfig}`);
  console.log(`  benchmark_configuration.json created: ${totalCreated.benchmarkConfig}`);
  console.log(`  error_description.md created: ${totalCreated.errorDescription}`);
  console.log(`  experiment_start_time.txt created: ${totalCreated.experimentStartTime}`);
  console.log(`  Directories skipped: ${totalCreated.skipped}`);
}

main();