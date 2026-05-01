#!/bin/bash

set -uo pipefail

# Configuration
WAIT_TIME=180  # 3 minutes between benchmarks
LOG_DIR="./benchmark_logs"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
MAIN_LOG="${LOG_DIR}/benchmark_run_${TIMESTAMP}.log"
RESULTS_DIR="/Users/jakob/WebstormProjects/BeFaaS-framework2/scripts/results/webservice"
PROJECT_ROOT="/Users/jakob/WebstormProjects/BeFaaS-framework2"
MIN_TOKEN_VALIDITY_SECONDS=7200  # 2 hours

# Export AWS settings
export AWS_REGION=us-east-1
export AWS_PROFILE="${AWS_PROFILE:-playground}"

# Track token renewal timing
LAST_TOKEN_CHECK=0
TOKEN_RENEWAL_INTERVAL=21600  # 6 hours in seconds

# Create log directory
mkdir -p "$LOG_DIR"

log() {
    local message="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$message" | tee -a "$MAIN_LOG"
}

log_separator() {
    echo "=============================================================================" | tee -a "$MAIN_LOG"
}

# Check if AWS credentials are valid by calling STS
check_aws_credentials_valid() {
    aws sts get-caller-identity --profile "$AWS_PROFILE" >/dev/null 2>&1
    return $?
}

# Try to estimate token expiry from credentials file
# Returns seconds remaining, or -1 if unknown
get_token_remaining_seconds() {
    local expiration
    # Check if aws_expiration is set for the profile
    expiration=$(grep -A20 "^\[${AWS_PROFILE}\]" ~/.aws/credentials 2>/dev/null \
        | grep "aws_expiration" | head -1 | cut -d= -f2- | xargs)

    if [ -n "$expiration" ]; then
        local expiry_epoch
        expiry_epoch=$(date -j -f "%a, %d %b %Y %H:%M:%S %Z" "$expiration" +%s 2>/dev/null \
            || date -j -f "%Y-%m-%dT%H:%M:%S" "$expiration" +%s 2>/dev/null \
            || echo "")

        if [ -n "$expiry_epoch" ]; then
            local now
            now=$(date +%s)
            echo $(( expiry_epoch - now ))
            return
        fi
    fi

    # If no expiration field, try to verify credentials are still valid
    if check_aws_credentials_valid; then
        echo "-1"  # Valid but unknown expiry
    else
        echo "0"  # Invalid
    fi
}

# Wait for the user to refresh AWS credentials
wait_for_valid_credentials() {
    local reason="$1"

    log "AWS TOKEN CHECK: $reason"
    log ""
    log "Please refresh your AWS credentials for profile '$AWS_PROFILE'."
    log "Update ~/.aws/credentials with fresh session token, then the script will continue."
    log ""

    # Play a sound to alert the user (macOS)
    afplay /System/Library/Sounds/Glass.aiff 2>/dev/null &

    local wait_count=0
    while true; do
        if check_aws_credentials_valid; then
            log "AWS credentials are now valid. Continuing..."
            LAST_TOKEN_CHECK=$(date +%s)
            return 0
        fi

        wait_count=$((wait_count + 1))
        if (( wait_count % 6 == 0 )); then
            local minutes=$((wait_count * 10 / 60))
            log "Still waiting for valid AWS credentials... (${minutes} min elapsed)"
            # Remind with sound every minute
            afplay /System/Library/Sounds/Glass.aiff 2>/dev/null &
        fi

        sleep 10
    done
}

# Ensure AWS token is valid and has enough remaining time
# Called before each benchmark
ensure_token_valid() {
    local remaining
    remaining=$(get_token_remaining_seconds)

    if [ "$remaining" = "0" ]; then
        wait_for_valid_credentials "Credentials are expired or invalid."
        return
    fi

    if [ "$remaining" != "-1" ] && [ "$remaining" -lt "$MIN_TOKEN_VALIDITY_SECONDS" ]; then
        local remaining_min=$((remaining / 60))
        wait_for_valid_credentials "Only ${remaining_min} minutes remaining (need at least $((MIN_TOKEN_VALIDITY_SECONDS / 60)) minutes)."
        return
    fi

    # Periodic renewal reminder (every 6 hours)
    local now
    now=$(date +%s)
    if [ "$LAST_TOKEN_CHECK" -gt 0 ] && (( now - LAST_TOKEN_CHECK > TOKEN_RENEWAL_INTERVAL )); then
        log "6-hour token renewal reminder: checking credentials..."
        if ! check_aws_credentials_valid; then
            wait_for_valid_credentials "Periodic check: credentials have expired."
            return
        fi
        log "Credentials still valid after 6h check."
        LAST_TOKEN_CHECK=$now
    fi

    if [ "$LAST_TOKEN_CHECK" = "0" ]; then
        LAST_TOKEN_CHECK=$now
    fi

    if [ "$remaining" != "-1" ]; then
        log "AWS token valid: ~$((remaining / 60)) minutes remaining"
    else
        log "AWS token valid (expiry time unknown)"
    fi
}

# Find the most recently created result folder matching a benchmark's params
find_result_folder() {
    local benchmark_args="$1"

    # Parse architecture from args
    local arch=""
    local auth=""
    if echo "$benchmark_args" | grep -q "\-a faas"; then arch="faas"; fi
    if echo "$benchmark_args" | grep -q "\-a microservices"; then arch="microservices"; fi
    if echo "$benchmark_args" | grep -q "\-a monolith"; then arch="monolith"; fi

    if echo "$benchmark_args" | grep -q "\-u none"; then auth="none"; fi
    if echo "$benchmark_args" | grep -q "\-u service-integrated-manual"; then auth="service-integrated-manual";
    elif echo "$benchmark_args" | grep -q "\-u service-integrated"; then auth="service-integrated"; fi
    if echo "$benchmark_args" | grep -q "\-u edge"; then auth="edge"; fi

    # Find the newest matching folder (non-hidden = completed)
    if [ -n "$arch" ] && [ -n "$auth" ]; then
        # shellcheck disable=SC2012
        ls -dt "${RESULTS_DIR}/${arch}_${auth}_"* 2>/dev/null | head -1
    else
        echo ""
    fi
}

import_results_background() {
    local folder="$1"
    if [ -z "$folder" ] || [ ! -d "$folder" ]; then
        log "DB IMPORT: No result folder found, skipping import"
        return
    fi

    local folder_name
    folder_name=$(basename "$folder")
    local import_log="${LOG_DIR}/db_import_${folder_name}_${TIMESTAMP}.log"

    log "DB IMPORT: Starting background import of $folder_name"
    log "DB IMPORT: Log: $import_log"

    (
        cd "$PROJECT_ROOT/scripts"
        # Source .env for DB credentials
        if [ -f "$PROJECT_ROOT/.env" ]; then
            export $(grep -v '^#' "$PROJECT_ROOT/.env" | xargs)
        fi
        export DB_TYPE=postgresql
        python3 -m db_import import "$folder" 2>&1 | tee "$import_log"
        log "DB IMPORT: Finished importing $folder_name (exit code: $?)"
    ) &

    log "DB IMPORT: Running in background (PID: $!)"
}

declare -a BENCHMARKS=(
    # "-a faas -u none --memory 512 --workload scnast.yml --destroy"
    # "-a faas -u service-integrated --memory 512 --workload scnast.yml --destroy"
    # "-a faas -u service-integrated-manual --memory 512 --workload scnast.yml --destroy"
    # "-a microservices -u none --cpu 1024 --memory-fargate 2048 --workload scnast.yml --destroy"
    # "-a microservices -u service-integrated --cpu 1024 --memory-fargate 2048 --workload scnast.yml --destroy"
    # "-a monolith -u none --memory-fargate 2048 --cpu 1024"
    # "-a monolith -u edge --memory-fargate 1024 --cpu 512"
    # "-a monolith -u edge --memory-fargate 2048 --cpu 1024"
    # "-a monolith -u service-integrated --memory-fargate 2048 --cpu 1024"
    # "-a monolith -u service-integrated --memory-fargate 8192 --cpu 4096"
    # "-a monolith -u service-integrated-manual --memory-fargate 512 --cpu 256 --algorithm bcrypt-hs256"
    # "-a monolith -u service-integrated-manual --memory-fargate 2048 --cpu 1024 --algorithm bcrypt-hs256"
    # "-a monolith -u service-integrated-manual --memory-fargate 8192 --cpu 4096 --algorithm bcrypt-hs256"
    # "-a monolith -u service-integrated-manual --memory-fargate 512 --cpu 256 --algorithm argon2id-eddsa"
    # "-a monolith -u service-integrated-manual --memory-fargate 8192 --cpu 4096 --algorithm argon2id-eddsa"
    # "-a monolith -u edge --memory-fargate 512 --cpu 256"
    # "-a monolith -u edge --memory-fargate 8192 --cpu 4096"
    # "-a microservices -u edge --memory-fargate 8192 --cpu 4096"
    # "-a microservices -u service-integrated-manual --memory-fargate 1024 --cpu 512 --algorithm bcrypt-hs256"
    # "-a faas -u none --memory 1024"
    # "-a faas -u edge --memory 1769"

    # "-a monolith -u service-integrated-manual --memory-fargate 8192 --cpu 4096 --algorithm argon2id-eddsa"
    # "-a monolith -u service-integrated-manual --memory-fargate 512 --cpu 256 --algorithm argon2id-eddsa"
    # "-a microservices --cpu --memory-fargate"
    # "-a microservices --cpu --memory-fargate"
    # "-a faas -u none --memory 1024"
    # "-a faas -u edge --memory 1769"
    # "-a faas -u edge-selective --memory 256"
    # "-a faas -u edge-selective --memory 512"
    # "-a faas -u edge-selective --memory 1024"
    # "-a faas -u edge-selective --memory 1769"

    # "-a microservices -u service-integrated-manual --memory-fargate 1024 --cpu 512 --algorithm bcrypt-hs256"
    # "-a microservices -u service-integrated-manual --memory-fargate 1024 --cpu 512 --algorithm bcrypt-hs256"
    # "-a microservices -u edge-selective --cpu 256 --memory-fargate 512"
    # "-a microservices -u edge-selective --cpu 512 --memory-fargate 1024"

    # "-a monolith -u edge-selective --cpu 256 --memory-fargate 512"
    # "-a monolith -u edge-selective --cpu 512 --memory-fargate 1024"
    # "-a monolith -u edge-selective --cpu 1024 --memory-fargate 2048"

    # "-a faas -u service-integrated-manual --memory 1769 --algorithm bcrypt-hs256"

    # "-a microservices -u edge-selective --cpu 4096 --memory-fargate 8192"
    # "-a microservices -u edge-selective --cpu 4096 --memory-fargate 8192"
    # "-a monolith -u edge-selective --cpu 4096 --memory-fargate 8192"
    # "-a monolith -u edge-selective --cpu 4096 --memory-fargate 8192"
    # "-a faas -u edge-selective --memory 1769"

    # "-a faas -u service-integrated --memory 256"
    # "-a faas -u edge --memory 256"
    # "-a faas -u service-integrated --memory 512"
    # "-a faas -u edge --memory 512"
    # "-a faas -u service-integrated-manual --memory 512 --algorithm bcrypt-hs256"
    # "-a faas -u service-integrated-manual --memory 512 --algorithm argon2id-eddsa"
    # "-a microservices -u service-integrated-manual --cpu 1024 --memory-fargate 2048 --algorithm bcrypt-hs256"
    # "-a microservices -u service-integrated --cpu 1024 --memory-fargate 2048"

    # "-a monolith -u edge ---cpu 1024 --memory-fargate 2048"
    # "-a microservices -u edge ---cpu 1024 --memory-fargate 2048"
    # "-a faas -u edge --memory 1024"
    # "-a monolith -u edge ---cpu 1024 --memory-fargate 2048"
    # "-a microservices -u edge ---cpu 1024 --memory-fargate 2048"
    # "-a faas -u edge --memory 1024"

    # "-a faas -u none --memory 1769"
    # "-a faas -u edge --memory 1769"
    # "-a faas -u edge --memory 1769"

    #"-a microservices -u none --memory-fargate 1024 --cpu 512"
    #"-a microservices -u edge --memory-fargate 1024 --cpu 512"
    #"-a microservices -u edge --memory-fargate 2048 --cpu 1024"
    #"-a microservices -u edge --memory-fargate 8192 --cpu 4096"
    #"-a microservices -u edge --memory-fargate 8192 --cpu 4096"

    #"-a monolith -u edge --memory 512 --cpu 256"
    #"-a monolith -u edge --memory 512 --cpu 256"
    #"-a monolith -u none --memory 2048 --cpu 1024"
    #"-a monolith -u edge --memory 2048 --cpu 1024"
    #"-a monolith -u edge --memory 8192 --cpu 4096"
    #"-a monolith -u edge --memory 8192 --cpu 4096"

    #"-a faas -u none --memory 1769 --with-cloudfront"
    #"-a microservices -u service-integrated-manual --cpu 512 --memory-fargate 1024 --with-cloudfront"
    #"-a microservices -u service-integrated-manual --cpu 1024 --memory-fargate 2048 --with-cloudfront"
    #"-a microservices -u service-integrated-manual --cpu 4096 --memory-fargate 8192 --with-cloudfront"
    #"-a microservices -u service-integrated --cpu 4096 --memory-fargate 8192 --with-cloudfront"
    #"-a microservices -u none --cpu 4096 --memory-fargate 8192 --with-cloudfront"
    #"-a monolith -u service-integrated-manual --cpu 4096 --memory-fargate 8192 --with-cloudfront"

    # Manual Argon2id/EdDSA with native argon2 binding -- pass 1
    "-a faas -u service-integrated-manual --memory 256 --algorithm argon2id-eddsa"
    "-a faas -u service-integrated-manual --memory 512 --algorithm argon2id-eddsa"
    "-a faas -u service-integrated-manual --memory 1024 --algorithm argon2id-eddsa"
    "-a microservices -u service-integrated-manual --cpu 256 --memory-fargate 512 --algorithm argon2id-eddsa"
    "-a microservices -u service-integrated-manual --cpu 512 --memory-fargate 1024 --algorithm argon2id-eddsa"
    "-a microservices -u service-integrated-manual --cpu 1024 --memory-fargate 2048 --algorithm argon2id-eddsa"
    "-a monolith -u service-integrated-manual --cpu 256 --memory-fargate 512 --algorithm argon2id-eddsa"
    "-a monolith -u service-integrated-manual --cpu 512 --memory-fargate 1024 --algorithm argon2id-eddsa"
    "-a monolith -u service-integrated-manual --cpu 1024 --memory-fargate 2048 --algorithm argon2id-eddsa"

    # Manual Argon2id/EdDSA with native argon2 binding -- pass 2
    "-a faas -u service-integrated-manual --memory 256 --algorithm argon2id-eddsa"
    "-a faas -u service-integrated-manual --memory 512 --algorithm argon2id-eddsa"
    "-a faas -u service-integrated-manual --memory 1024 --algorithm argon2id-eddsa"
    "-a microservices -u service-integrated-manual --cpu 256 --memory-fargate 512 --algorithm argon2id-eddsa"
    "-a microservices -u service-integrated-manual --cpu 512 --memory-fargate 1024 --algorithm argon2id-eddsa"
    "-a microservices -u service-integrated-manual --cpu 1024 --memory-fargate 2048 --algorithm argon2id-eddsa"
    "-a monolith -u service-integrated-manual --cpu 256 --memory-fargate 512 --algorithm argon2id-eddsa"
    "-a monolith -u service-integrated-manual --cpu 512 --memory-fargate 1024 --algorithm argon2id-eddsa"
    "-a monolith -u service-integrated-manual --cpu 1024 --memory-fargate 2048 --algorithm argon2id-eddsa"

    "-a faas -u service-integrated-manual --memory 1769 --algorithm argon2id-eddsa"
    "-a microservices -u service-integrated-manual --cpu 4096 --memory-fargate 8192 --algorithm argon2id-eddsa"
    "-a monolith -u service-integrated-manual --cpu 4096 --memory-fargate 8192 --algorithm argon2id-eddsa"
    "-a faas -u service-integrated-manual --memory 1769 --algorithm argon2id-eddsa"
    "-a microservices -u service-integrated-manual --cpu 4096 --memory-fargate 8192 --algorithm argon2id-eddsa"
    "-a monolith -u service-integrated-manual --cpu 4096 --memory-fargate 8192 --algorithm argon2id-eddsa"

    "-a faas -u edge --memory 1769"
    "-a microservices -u edge --cpu 1024 --memory-fargate 1024"
    "-a monolith -u edge --cpu 1024 --memory-fargate 1024"
    "-a monolith -u edge --cpu 1024 --memory-fargate 2048"
    "-a monolith -u edge --cpu 512 --memory-fargate 1024"
    "-a monolith -u edge --cpu 4096 --memory-fargate 8192"
    "-a microservices -u edge --cpu 256 --memory-fargate 512"
    "-a faas -u edge --memory 256"
    "-a faas -u edge-selective --memory 256"
    "-a faas -u edge-selective --memory 512"
    "-a microservices -u edge-selective --cpu 256  --memory-fargate 512"
    "-a microservices -u edge-selective --cpu 512  --memory-fargate 1024"
    "-a microservices -u edge-selective --cpu 1024 --memory-fargate 2048"
    "-a microservices -u edge-selective --cpu 4096 --memory-fargate 8192"
    "-a monolith -u edge-selective --cpu 256  --memory-fargate 512"
    "-a monolith -u edge-selective --cpu 512  --memory-fargate 1024"
    "-a monolith -u edge-selective --cpu 1024 --memory-fargate 2048"
    "-a monolith -u edge-selective --cpu 4096 --memory-fargate 8192"
)

log_separator
log "BATCH BENCHMARK SUITE STARTED"
log "AWS_PROFILE: $AWS_PROFILE"
log "AWS_REGION: $AWS_REGION"
log "Total benchmarks: ${#BENCHMARKS[@]}"
log "Min token validity: $((MIN_TOKEN_VALIDITY_SECONDS / 60)) minutes"
log "Wait between benchmarks: ${WAIT_TIME}s"
log_separator

# Initial credentials check
ensure_token_valid

TOTAL=${#BENCHMARKS[@]}
PASSED=0
FAILED=0
SKIPPED=0

for i in "${!BENCHMARKS[@]}"; do
    BENCHMARK="${BENCHMARKS[$i]}"
    RUN_NUMBER=$((i + 1))
    BENCH_LOG="${LOG_DIR}/benchmark_${TIMESTAMP}_run${RUN_NUMBER}.log"

    log_separator
    log "BENCHMARK $RUN_NUMBER/$TOTAL"
    log "Command: node experiment.js $BENCHMARK"
    log "Log: $BENCH_LOG"
    log "Started: $(date)"

    # Check token before each benchmark
    ensure_token_valid

    # Record folder state before benchmark (to detect new results)
    local_folders_before=$(ls -d "${RESULTS_DIR}"/*/ 2>/dev/null | wc -l)

    # Run the benchmark
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
    DURATION_MIN=$((DURATION / 60))

    log "Finished: $(date)"
    log "Duration: ${DURATION_MIN}m ${DURATION}s"
    log "Status: $STATUS"

    # Start background db_import for the result folder
    result_folder=$(find_result_folder "$BENCHMARK")
    if [ -n "$result_folder" ]; then
        import_results_background "$result_folder"
    else
        log "DB IMPORT: Could not find result folder for this benchmark"
    fi

    # Wait between benchmarks (except after the last one)
    if [ "$RUN_NUMBER" -lt "$TOTAL" ]; then
        log "Waiting ${WAIT_TIME}s before next benchmark..."
        log "Next benchmark: $(date -v+${WAIT_TIME}S 2>/dev/null || date -d "+${WAIT_TIME} seconds" 2>/dev/null || echo 'soon')"
        sleep "$WAIT_TIME"
    fi
done

log_separator
log "BATCH BENCHMARK SUITE COMPLETED"
log "Total: $TOTAL | Passed: $PASSED | Failed: $FAILED"
log "Logs: $LOG_DIR"

# Check if any background imports are still running
BG_JOBS=$(jobs -r 2>/dev/null | wc -l)
if [ "$BG_JOBS" -gt 0 ]; then
    log "Note: $BG_JOBS background db_import job(s) still running"
    log "Check logs in $LOG_DIR for import status"
fi

log_separator

exit 0
