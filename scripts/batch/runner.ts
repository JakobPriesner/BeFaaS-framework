#!/usr/bin/env npx ts-node

/**
 * Batch Benchmark Runner
 *
 * Runs multiple benchmark combinations sequentially, generating all possible
 * combinations from a configuration file.
 *
 * Usage:
 *   npx ts-node scripts/batch/runner.ts --config <config-file> [options]
 *
 * Options:
 *   --config, -c     Path to batch configuration file (required)
 *   --dry-run        Print combinations without running
 *   --list           List all combinations and exit
 *   --start-from     Start from a specific combination ID
 *   --skip           Skip specific combination IDs (comma-separated)
 *   --help, -h       Show help
 */

import * as fs from 'fs';
import * as path from 'path';
import { spawn, SpawnOptions } from 'child_process';
import {
  BatchConfig,
  BenchmarkCombination,
  BenchmarkResult,
  BatchRunSummary,
  BenchmarkStatus,
} from './types';
import { loadBatchConfig } from './config-validator';
import {
  generateAllCombinations,
  calculateTotalCombinations,
  printCombinationSummary,
} from './combination-generator';

// =============================================================================
// CLI Argument Parsing
// =============================================================================

interface CliArgs {
  configPath: string;
  dryRun: boolean;
  listOnly: boolean;
  startFrom?: string;
  skipIds: string[];
  help: boolean;
}

function printUsage(): void {
  console.log(`
Batch Benchmark Runner
======================

Runs multiple benchmark combinations sequentially from a configuration file.

Usage:
  npx ts-node scripts/batch/runner.ts --config <config-file> [options]

Required:
  --config, -c <path>    Path to batch configuration file (.json or .ts)

Options:
  --dry-run              Print what would be run without actually running
  --list                 List all combinations and exit
  --start-from <id>      Start from a specific combination ID (skip previous)
  --skip <ids>           Skip specific combination IDs (comma-separated)
  --help, -h             Show this help message

Examples:
  # Run all benchmarks from config
  npx ts-node scripts/batch/runner.ts -c configs/full-benchmark.ts

  # List all combinations without running
  npx ts-node scripts/batch/runner.ts -c configs/full-benchmark.ts --list

  # Dry run to see what would be executed
  npx ts-node scripts/batch/runner.ts -c configs/full-benchmark.ts --dry-run

  # Resume from a specific combination
  npx ts-node scripts/batch/runner.ts -c configs/full-benchmark.ts --start-from faas_none_mem512_bundle-full

  # Skip specific combinations
  npx ts-node scripts/batch/runner.ts -c configs/full-benchmark.ts --skip faas_none_mem128_bundle-full,faas_none_mem256_bundle-full
`);
}

function parseCliArgs(args: string[]): CliArgs {
  const result: CliArgs = {
    configPath: '',
    dryRun: false,
    listOnly: false,
    skipIds: [],
    help: false,
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];

    switch (arg) {
      case '--help':
      case '-h':
        result.help = true;
        break;
      case '--config':
      case '-c':
        result.configPath = args[++i];
        break;
      case '--dry-run':
        result.dryRun = true;
        break;
      case '--list':
        result.listOnly = true;
        break;
      case '--start-from':
        result.startFrom = args[++i];
        break;
      case '--skip':
        result.skipIds = args[++i].split(',').map(s => s.trim());
        break;
      default:
        if (arg.startsWith('-')) {
          console.error(`Unknown argument: ${arg}`);
          printUsage();
          process.exit(1);
        }
    }
  }

  return result;
}

// =============================================================================
// Benchmark Execution
// =============================================================================

/**
 * Run a single experiment using the existing experiment.js script
 */
async function runExperiment(
  combination: BenchmarkCombination,
  config: BatchConfig
): Promise<void> {
  const scriptPath = path.join(__dirname, '..', 'experiment.js');

  const args = [
    scriptPath,
    '--architecture', combination.architecture,
    '--auth', combination.auth,
    '--experiment', combination.experiment,
    '--workload', combination.workload,
    '--output-dir', combination.outputDir,
  ];

  // Add Lambda memory for FaaS
  if (combination.lambdaMemory !== undefined) {
    args.push('--memory', String(combination.lambdaMemory));
  }

  // Add destroy flag if configured
  if (config.global.destroyAfterBenchmark) {
    args.push('--destroy');
  }

  // Add skip metrics flag if configured
  if (config.global.skipMetrics) {
    args.push('--skip-metrics');
  }

  // TODO: Handle bundle size configuration
  // This would require modifying the build process to support bundle size
  if (combination.bundleSize !== undefined) {
    // Set environment variable for build process
    process.env.BUNDLE_SIZE_STRATEGY = combination.bundleSize;
  }

  // TODO: Handle Fargate hardware configuration
  // This would require modifying the deploy process to support Fargate config
  if (combination.fargateConfig !== undefined) {
    process.env.FARGATE_CPU = String(combination.fargateConfig.cpu);
    process.env.FARGATE_MEMORY = String(combination.fargateConfig.memory);
  }

  return new Promise((resolve, reject) => {
    console.log(`\nExecuting: node ${args.join(' ')}\n`);

    const spawnOptions: SpawnOptions = {
      stdio: 'inherit',
      cwd: path.join(__dirname, '..', '..'),
      env: { ...process.env },
    };

    const child = spawn('node', args, spawnOptions);

    child.on('close', (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`Experiment exited with code ${code}`));
      }
    });

    child.on('error', (err) => {
      reject(err);
    });
  });
}

/**
 * Delay helper
 */
function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Format duration in human readable format
 */
function formatDuration(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);

  if (hours > 0) {
    return `${hours}h ${minutes % 60}m ${seconds % 60}s`;
  } else if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`;
  } else {
    return `${seconds}s`;
  }
}

/**
 * Print a separator line
 */
function printSeparator(char: string = '='): void {
  console.log(char.repeat(80));
}

/**
 * Run all benchmarks
 */
async function runBatchBenchmarks(
  config: BatchConfig,
  combinations: BenchmarkCombination[],
  options: {
    dryRun: boolean;
    startFrom?: string;
    skipIds: string[];
  }
): Promise<BatchRunSummary> {
  const summary: BatchRunSummary = {
    configName: config.name,
    totalCombinations: combinations.length,
    completed: 0,
    failed: 0,
    skipped: 0,
    startTime: new Date(),
    results: [],
  };

  // Filter combinations based on start-from and skip options
  let startIndex = 0;
  if (options.startFrom) {
    startIndex = combinations.findIndex(c => c.id === options.startFrom);
    if (startIndex === -1) {
      console.error(`Error: Combination ID "${options.startFrom}" not found`);
      process.exit(1);
    }
    console.log(`Starting from combination: ${options.startFrom} (index ${startIndex})`);
  }

  const filteredCombinations = combinations.slice(startIndex).filter(
    c => !options.skipIds.includes(c.id)
  );

  console.log(`\nWill run ${filteredCombinations.length} benchmarks`);
  if (startIndex > 0) {
    console.log(`  Skipping first ${startIndex} combinations (start-from)`);
  }
  if (options.skipIds.length > 0) {
    console.log(`  Skipping ${options.skipIds.length} combinations (skip IDs)`);
  }

  printSeparator();

  for (let i = 0; i < filteredCombinations.length; i++) {
    const combination = filteredCombinations[i];
    const benchmarkIndex = i + 1;

    printSeparator();
    console.log(`\nBENCHMARK ${benchmarkIndex}/${filteredCombinations.length}`);
    console.log(`ID: ${combination.id}`);
    console.log(`Architecture: ${combination.architecture}`);
    console.log(`Auth: ${combination.auth}`);
    if (combination.lambdaMemory) {
      console.log(`Lambda Memory: ${combination.lambdaMemory} MB`);
    }
    if (combination.bundleSize) {
      console.log(`Bundle Size: ${combination.bundleSize}`);
    }
    if (combination.fargateConfig) {
      console.log(`Fargate CPU: ${combination.fargateConfig.cpu}`);
      console.log(`Fargate Memory: ${combination.fargateConfig.memory} MB`);
    }
    console.log(`Output: ${combination.outputDir}`);
    printSeparator();

    const result: BenchmarkResult = {
      combination,
      status: BenchmarkStatus.Pending,
      startTime: new Date(),
      retryCount: 0,
    };

    if (options.dryRun) {
      console.log('\n[DRY RUN] Would execute benchmark\n');
      result.status = BenchmarkStatus.Skipped;
      result.endTime = new Date();
      summary.skipped++;
    } else {
      const maxRetries = config.global.maxRetries || 0;
      let success = false;

      while (!success && result.retryCount <= maxRetries) {
        if (result.retryCount > 0) {
          console.log(`\nRetry attempt ${result.retryCount}/${maxRetries}...`);
        }

        try {
          result.status = BenchmarkStatus.Running;
          await runExperiment(combination, config);
          result.status = BenchmarkStatus.Completed;
          result.endTime = new Date();
          result.durationMs = result.endTime.getTime() - result.startTime.getTime();
          summary.completed++;
          success = true;

          console.log(`\n✓ Benchmark completed in ${formatDuration(result.durationMs)}`);
        } catch (error) {
          result.retryCount++;
          const errorMessage = error instanceof Error ? error.message : String(error);

          if (result.retryCount <= maxRetries) {
            console.error(`\nBenchmark failed: ${errorMessage}`);
            console.log(`Will retry (${result.retryCount}/${maxRetries})...`);
            await delay(5000); // Wait 5 seconds before retry
          } else {
            result.status = BenchmarkStatus.Failed;
            result.endTime = new Date();
            result.durationMs = result.endTime.getTime() - result.startTime.getTime();
            result.error = errorMessage;
            summary.failed++;

            console.error(`\n✗ Benchmark failed after ${result.retryCount - 1} retries: ${errorMessage}`);

            if (!config.global.continueOnFailure) {
              console.error('\nStopping batch due to failure (continueOnFailure is false)');
              summary.results.push(result);
              break;
            }
          }
        }
      }
    }

    summary.results.push(result);

    // Delay between benchmarks if configured
    if (
      i < filteredCombinations.length - 1 &&
      config.global.delayBetweenBenchmarks &&
      !options.dryRun
    ) {
      console.log(`\nWaiting ${config.global.delayBetweenBenchmarks / 1000}s before next benchmark...`);
      await delay(config.global.delayBetweenBenchmarks);
    }

    // Stop if failed and continueOnFailure is false
    if (result.status === BenchmarkStatus.Failed && !config.global.continueOnFailure) {
      break;
    }
  }

  summary.endTime = new Date();
  summary.totalDurationMs = summary.endTime.getTime() - summary.startTime.getTime();

  return summary;
}

/**
 * Print final summary
 */
function printFinalSummary(summary: BatchRunSummary): void {
  printSeparator('=');
  console.log('\nBATCH RUN SUMMARY');
  printSeparator('=');

  console.log(`\nConfiguration: ${summary.configName}`);
  console.log(`Total combinations: ${summary.totalCombinations}`);
  console.log(`Completed: ${summary.completed}`);
  console.log(`Failed: ${summary.failed}`);
  console.log(`Skipped: ${summary.skipped}`);

  if (summary.totalDurationMs) {
    console.log(`Total duration: ${formatDuration(summary.totalDurationMs)}`);
  }

  if (summary.failed > 0) {
    console.log('\nFailed benchmarks:');
    for (const result of summary.results) {
      if (result.status === BenchmarkStatus.Failed) {
        console.log(`  - ${result.combination.id}: ${result.error}`);
      }
    }
  }

  printSeparator('=');
}

/**
 * Save summary to file
 */
function saveSummary(summary: BatchRunSummary, outputDir: string): void {
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  const summaryPath = path.join(outputDir, 'batch-summary.json');
  fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
  console.log(`\nSummary saved to: ${summaryPath}`);
}

// =============================================================================
// Main Entry Point
// =============================================================================

async function main(): Promise<void> {
  const args = parseCliArgs(process.argv.slice(2));

  if (args.help) {
    printUsage();
    process.exit(0);
  }

  if (!args.configPath) {
    console.error('Error: --config is required');
    printUsage();
    process.exit(1);
  }

  // Resolve config path
  const configPath = path.resolve(args.configPath);

  console.log('Loading batch configuration...');
  const config = loadBatchConfig(configPath);

  console.log(`\nConfiguration: ${config.name}`);
  if (config.description) {
    console.log(`Description: ${config.description}`);
  }

  // Generate combinations
  const combinations = generateAllCombinations(config);

  if (args.listOnly) {
    printCombinationSummary(combinations);
    console.log(`\nTotal estimated benchmarks: ${combinations.length}`);
    process.exit(0);
  }

  printCombinationSummary(combinations);

  if (args.dryRun) {
    console.log('\n*** DRY RUN MODE - No benchmarks will be executed ***\n');
  }

  // Confirm before running
  if (!args.dryRun) {
    console.log('\nPress Ctrl+C within 5 seconds to cancel...');
    await delay(5000);
  }

  // Run benchmarks
  const summary = await runBatchBenchmarks(config, combinations, {
    dryRun: args.dryRun,
    startFrom: args.startFrom,
    skipIds: args.skipIds,
  });

  // Print and save summary
  printFinalSummary(summary);

  const outputBaseDir = config.global.outputBaseDir || 'results';
  saveSummary(summary, path.join(outputBaseDir, 'batch-runs'));

  // Exit with error code if any benchmarks failed
  if (summary.failed > 0) {
    process.exit(1);
  }
}

main().catch((error) => {
  console.error('Batch runner failed:', error);
  process.exit(1);
});