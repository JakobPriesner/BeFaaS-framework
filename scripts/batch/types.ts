/**
 * Batch Benchmark Runner - Type Definitions
 *
 * This file contains all TypeScript interfaces and types for the batch
 * benchmark runner. Using interfaces ensures type safety and clear contracts
 * for all configuration options.
 */

// =============================================================================
// Architecture Types
// =============================================================================

/**
 * Supported architecture types
 */
export const Architecture = {
  FaaS: 'faas',
  Microservices: 'microservices',
  Monolith: 'monolith',
} as const;

export type ArchitectureType = typeof Architecture[keyof typeof Architecture];

// =============================================================================
// Authentication Types
// =============================================================================

/**
 * Supported authentication strategies
 */
export const AuthStrategy = {
  None: 'none',
  ServiceIntegrated: 'service-integrated',
  Edge: 'edge',
} as const;

export type AuthStrategyType = typeof AuthStrategy[keyof typeof AuthStrategy];

// =============================================================================
// Hardware Configuration Types
// =============================================================================

/**
 * Lambda memory configurations in MB
 */
export const LambdaMemory = {
  MB_128: 128,
  MB_256: 256,
  MB_512: 512,
  MB_1024: 1024,
  MB_2048: 2048,
  MB_3072: 3072,
  MB_4096: 4096,
} as const;

export type LambdaMemoryType = typeof LambdaMemory[keyof typeof LambdaMemory];

/**
 * ECS Fargate CPU configurations in vCPU units
 */
export const FargateCPU = {
  VCPU_0_25: 256,
  VCPU_0_5: 512,
  VCPU_1: 1024,
  VCPU_2: 2048,
  VCPU_4: 4096,
} as const;

export type FargateCPUType = typeof FargateCPU[keyof typeof FargateCPU];

/**
 * ECS Fargate memory configurations in MB
 */
export const FargateMemory = {
  MB_512: 512,
  MB_1024: 1024,
  MB_2048: 2048,
  MB_4096: 4096,
  MB_8192: 8192,
} as const;

export type FargateMemoryType = typeof FargateMemory[keyof typeof FargateMemory];

/**
 * Fargate hardware configuration combining CPU and memory
 */
export interface FargateHardwareConfig {
  cpu: FargateCPUType;
  memory: FargateMemoryType;
}

// =============================================================================
// Bundle Size Types (Lambda-specific)
// =============================================================================

/**
 * Bundle size strategy for Lambda deployments
 */
export const BundleSize = {
  /** Include all code in each function */
  Full: 'full',
  /** Include only necessary code for each function */
  NecessaryOnly: 'necessary-only',
} as const;

export type BundleSizeType = typeof BundleSize[keyof typeof BundleSize];

// =============================================================================
// Experiment Types
// =============================================================================

/**
 * Available experiment types
 */
export const ExperimentType = {
  Webservice: 'webservice',
  IoT: 'iot',
  SmartFactory: 'smartFactory',
  Streaming: 'streaming',
  Topics: 'topics',
  Test: 'test',
} as const;

export type ExperimentTypeValue = typeof ExperimentType[keyof typeof ExperimentType];

// =============================================================================
// Configuration Interfaces
// =============================================================================

/**
 * Global options that apply to all architectures
 */
export interface GlobalOptions {
  /** Authentication strategies to test */
  authStrategies: AuthStrategyType[];

  /** Experiment type to run */
  experiment: ExperimentTypeValue;

  /** Workload file to use */
  workload?: string;

  /** Whether to destroy infrastructure after each benchmark */
  destroyAfterBenchmark?: boolean;

  /** Whether to skip metrics collection */
  skipMetrics?: boolean;

  /** Custom output base directory */
  outputBaseDir?: string;

  /** Delay between benchmarks in milliseconds */
  delayBetweenBenchmarks?: number;

  /** Maximum retries on failure */
  maxRetries?: number;

  /** Continue on failure instead of stopping */
  continueOnFailure?: boolean;
}

/**
 * FaaS (Lambda) specific options
 */
export interface FaaSOptions {
  /** Enable FaaS architecture in this batch */
  enabled: boolean;

  /** Lambda memory configurations to test */
  memoryConfigs: LambdaMemoryType[];

  /** Bundle size strategies to test */
  bundleSizes: BundleSizeType[];
}

/**
 * Microservices (ECS Fargate) specific options
 */
export interface MicroservicesOptions {
  /** Enable Microservices architecture in this batch */
  enabled: boolean;

  /** Fargate hardware configurations to test */
  hardwareConfigs: FargateHardwareConfig[];
}

/**
 * Monolith (ECS Fargate) specific options
 */
export interface MonolithOptions {
  /** Enable Monolith architecture in this batch */
  enabled: boolean;

  /** Fargate hardware configurations to test */
  hardwareConfigs: FargateHardwareConfig[];
}

/**
 * Architecture-specific options container
 */
export interface ArchitectureOptions {
  faas?: FaaSOptions;
  microservices?: MicroservicesOptions;
  monolith?: MonolithOptions;
}

/**
 * Complete batch configuration
 */
export interface BatchConfig {
  /** Configuration name/identifier */
  name: string;

  /** Description of this batch run */
  description?: string;

  /** Global options applying to all architectures */
  global: GlobalOptions;

  /** Architecture-specific options */
  architectures: ArchitectureOptions;
}

// =============================================================================
// Benchmark Combination Types
// =============================================================================

/**
 * A single benchmark combination to run
 */
export interface BenchmarkCombination {
  /** Unique identifier for this combination */
  id: string;

  /** Architecture type */
  architecture: ArchitectureType;

  /** Authentication strategy */
  auth: AuthStrategyType;

  /** Experiment type */
  experiment: ExperimentTypeValue;

  /** Workload file */
  workload: string;

  /** Lambda memory (only for FaaS) */
  lambdaMemory?: LambdaMemoryType;

  /** Bundle size strategy (only for FaaS) */
  bundleSize?: BundleSizeType;

  /** Fargate hardware config (only for Microservices/Monolith) */
  fargateConfig?: FargateHardwareConfig;

  /** Output directory for this benchmark */
  outputDir: string;
}

/**
 * Status of a benchmark run
 */
export const BenchmarkStatus = {
  Pending: 'pending',
  Running: 'running',
  Completed: 'completed',
  Failed: 'failed',
  Skipped: 'skipped',
} as const;

export type BenchmarkStatusType = typeof BenchmarkStatus[keyof typeof BenchmarkStatus];

/**
 * Result of a single benchmark run
 */
export interface BenchmarkResult {
  /** The combination that was run */
  combination: BenchmarkCombination;

  /** Status of the benchmark */
  status: BenchmarkStatusType;

  /** Start time */
  startTime: Date;

  /** End time */
  endTime?: Date;

  /** Duration in milliseconds */
  durationMs?: number;

  /** Error message if failed */
  error?: string;

  /** Number of retry attempts */
  retryCount: number;
}

/**
 * Overall batch run summary
 */
export interface BatchRunSummary {
  /** Configuration name */
  configName: string;

  /** Total number of combinations */
  totalCombinations: number;

  /** Number of completed benchmarks */
  completed: number;

  /** Number of failed benchmarks */
  failed: number;

  /** Number of skipped benchmarks */
  skipped: number;

  /** Batch start time */
  startTime: Date;

  /** Batch end time */
  endTime?: Date;

  /** Total duration in milliseconds */
  totalDurationMs?: number;

  /** Individual results */
  results: BenchmarkResult[];
}

// =============================================================================
// Validation Types
// =============================================================================

/**
 * Validation result for configuration
 */
export interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

// =============================================================================
// Helper Type Guards
// =============================================================================

export function isArchitectureType(value: string): value is ArchitectureType {
  return Object.values(Architecture).includes(value as ArchitectureType);
}

export function isAuthStrategyType(value: string): value is AuthStrategyType {
  return Object.values(AuthStrategy).includes(value as AuthStrategyType);
}

export function isExperimentType(value: string): value is ExperimentTypeValue {
  return Object.values(ExperimentType).includes(value as ExperimentTypeValue);
}

export function isLambdaMemoryType(value: number): value is LambdaMemoryType {
  return Object.values(LambdaMemory).includes(value as LambdaMemoryType);
}

export function isBundleSizeType(value: string): value is BundleSizeType {
  return Object.values(BundleSize).includes(value as BundleSizeType);
}