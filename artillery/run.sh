#!/bin/sh

set -xeuo pipefail

# Pre-register users in Redis (if REDIS_ENDPOINT is set and auth mode is service-integrated or none)
if [ -n "${REDIS_ENDPOINT:-}" ] && { [ "${AUTH_MODE:-}" = "service-integrated" ] || [ "${AUTH_MODE:-}" = "none" ]; }; then
  echo "Running Redis user preregistration..."
  node /workload/preregister-redis.js
fi

# Run Artillery benchmark
artillery run -v "$(cat ./variables.json || echo -n "{}")" ./workload.yml
