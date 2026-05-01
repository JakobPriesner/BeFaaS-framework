#!/usr/bin/env bash
#
# Re-run log-analyzer.js against runs whose log-analysis.json has auth_metrics=null
# in s3://jakobs-benchmark-results/webservice/. Pulls artillery.log + aws.log +
# deployment_id.txt, regenerates log-analysis.json locally, and pushes it back.
#
# Usage:
#   scripts/reanalyze-s3-runs.sh <run-id> [<run-id> ...]
#   scripts/reanalyze-s3-runs.sh --all     # reanalyze every run listed in runs.txt
#   scripts/reanalyze-s3-runs.sh --dry-run ...
#
# Expects AWS_PROFILE=playground in the environment (or a working default
# profile with s3:GetObject/PutObject on the bucket).

set -euo pipefail

BUCKET="s3://jakobs-benchmark-results/webservice"
WORK_DIR="${REANALYZE_WORK_DIR:-/tmp/reanalyze}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

RUN_IDS=("$@")
if [[ ${#RUN_IDS[@]} -eq 1 && "${RUN_IDS[0]}" == "--all" ]]; then
  if [[ ! -f /tmp/s3_logs/null_runs_clean.txt ]]; then
    echo "Expected run list at /tmp/s3_logs/null_runs_clean.txt — generate it first." >&2
    exit 1
  fi
  mapfile -t RUN_IDS < /tmp/s3_logs/null_runs_clean.txt
fi

if [[ ${#RUN_IDS[@]} -eq 0 ]]; then
  echo "Usage: $0 [--dry-run] <run-id> [<run-id> ...] | --all" >&2
  exit 1
fi

mkdir -p "${WORK_DIR}"

ok=0
fail=0
skipped=0
for RUN_ID in "${RUN_IDS[@]}"; do
  echo "=== ${RUN_ID} ==="
  RUN_DIR="${WORK_DIR}/${RUN_ID}"
  LOGS_DIR="${RUN_DIR}/logs"
  ANALYSIS_DIR="${RUN_DIR}/analysis"

  mkdir -p "${LOGS_DIR}" "${ANALYSIS_DIR}"

  aws s3 sync \
    "${BUCKET}/${RUN_ID}/logs/" "${LOGS_DIR}/" \
    --exclude '*' \
    --include 'artillery.log' \
    --include 'aws.log' \
    --include 'deployment_id.txt' \
    --only-show-errors

  if [[ ! -s "${LOGS_DIR}/artillery.log" ]]; then
    echo "  SKIP: no artillery.log for ${RUN_ID}"
    skipped=$((skipped + 1))
    continue
  fi

  if ! node "${REPO_ROOT}/scripts/experiment/log-analyzer-cli.js" "${RUN_DIR}"; then
    echo "  FAIL: analyzer exited non-zero for ${RUN_ID}"
    fail=$((fail + 1))
    continue
  fi

  local_json="${ANALYSIS_DIR}/log-analysis.json"
  if [[ ! -s "${local_json}" ]]; then
    echo "  FAIL: no log-analysis.json produced for ${RUN_ID}"
    fail=$((fail + 1))
    continue
  fi

  if python3 -c "import json,sys; d=json.load(open('${local_json}')); sys.exit(0 if d.get('auth_metrics') else 2)"; then
    :
  else
    echo "  WARN: auth_metrics still null in ${RUN_ID} — uploading anyway (likely genuine no-auth run)"
  fi

  if [[ ${DRY_RUN} -eq 1 ]]; then
    echo "  [dry-run] would upload ${local_json} -> ${BUCKET}/${RUN_ID}/analysis/log-analysis.json"
  else
    aws s3 cp "${local_json}" "${BUCKET}/${RUN_ID}/analysis/log-analysis.json" --only-show-errors
  fi

  ok=$((ok + 1))
done

echo
echo "Done: ok=${ok} fail=${fail} skipped=${skipped}"