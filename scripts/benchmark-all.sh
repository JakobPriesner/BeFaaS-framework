#!/bin/bash

# =============================================================================
# Benchmark Runner Script
# =============================================================================

# Configuration
WAIT_TIME=180  # 3 minutes in seconds
LOG_DIR="./benchmark_logs"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
MAIN_LOG="${LOG_DIR}/benchmark_run_${TIMESTAMP}.log"

# Export AWS Region
export AWS_REGION=us-east-1

# Create log directory if it doesn't exist
mkdir -p "$LOG_DIR"

# =============================================================================
# Logging Functions
# =============================================================================

log() {
    local message="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$message" | tee -a "$MAIN_LOG"
}

log_separator() {
    echo "=============================================================================" | tee -a "$MAIN_LOG"
}

# =============================================================================
# Benchmark Definitions
# =============================================================================

declare -a BENCHMARKS=(
    "-a faas -u none --memory 512 --workload scnast.yml"
    "-a faas -u service-integrated-manual --memory 256 --workload scnast.yml"
    "-a faas -u service-integrated --memory 512 --workload scnast.yml"
    "-a faas -u service-integrated-manual --memory 512 --workload scnast.yml"
)

# =============================================================================
# Main Execution
# =============================================================================

log_separator
log "BENCHMARK SUITE STARTED"
log "AWS_REGION: $AWS_REGION"
log "Total benchmarks to run: ${#BENCHMARKS[@]}"
log "Wait time between benchmarks: ${WAIT_TIME} seconds"
log_separator

TOTAL=${#BENCHMARKS[@]}
PASSED=0
FAILED=0

for i in "${!BENCHMARKS[@]}"; do
    BENCHMARK="${BENCHMARKS[$i]}"
    RUN_NUMBER=$((i + 1))

    # Create individual log file for this benchmark
    BENCH_LOG="${LOG_DIR}/benchmark_${TIMESTAMP}_run${RUN_NUMBER}.log"

    log_separator
    log "BENCHMARK $RUN_NUMBER/$TOTAL"
    log "Command: node experiment.js $BENCHMARK"
    log "Individual log: $BENCH_LOG"
    log "Started at: $(date)"

    # Run the benchmark and capture output
    START_TIME=$(date +%s)

    if node experiment.js $BENCHMARK 2>&1 | tee -a "$BENCH_LOG"; then
        EXIT_CODE=0
        STATUS="PASSED"
        ((PASSED++))
    else
        EXIT_CODE=$?
        STATUS="FAILED (exit code: $EXIT_CODE)"
        ((FAILED++))
    fi

    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    log "Finished at: $(date)"
    log "Duration: ${DURATION} seconds"
    log "Status: $STATUS"

    # Wait between benchmarks (except after the last one)
    if [ $RUN_NUMBER -lt $TOTAL ]; then
        log "Waiting ${WAIT_TIME} seconds before next benchmark..."
        log "Next benchmark starts at: $(date -d "+${WAIT_TIME} seconds" 2>/dev/null || date -v+${WAIT_TIME}S)"
        sleep $WAIT_TIME
    fi
done

# =============================================================================
# Summary
# =============================================================================

log_separator
log "BENCHMARK SUITE COMPLETED"
log "Total: $TOTAL | Passed: $PASSED | Failed: $FAILED"
log "Logs saved to: $LOG_DIR"
log_separator

# Exit with failure if any benchmark failed
if [ $FAILED -gt 0 ]; then
    exit 1
fi

exit 0