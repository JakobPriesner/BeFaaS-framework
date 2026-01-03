#!/bin/bash

set -euo pipefail

echo "Getting Cognito CloudTrail logs for deployment: ${BEFAAS_DEPLOYMENT_ID}" | chalk magenta
echo "Using AWS region: ${AWS_DEFAULT_REGION:-${AWS_REGION:-us-east-1}}" | chalk blue

# Setup timestamp filtering for CloudTrail (requires ISO format)
if [ ! -z "${EXPERIMENT_START_TIME:-}" ]; then
  # Convert milliseconds to ISO format for CloudTrail
  start_time_iso=$(date -d "@$((EXPERIMENT_START_TIME/1000))" -Iseconds)
  end_time_iso=$(date -d "@$((EXPERIMENT_END_TIME:-$(date +%s)000)/1000))" -Iseconds)

  echo "CloudTrail filtering from: $start_time_iso to $end_time_iso" | chalk blue

  # Collect Cognito API events from CloudTrail
  echo "Collecting Cognito authentication events..." | chalk green

  # Create temporary file for CloudTrail events
  cloudtrail_temp="$logdir/cognito_cloudtrail_temp.json"

  # Fetch Cognito-related CloudTrail events with timestamp filtering
  aws cloudtrail lookup-events \
    --lookup-attributes AttributeKey=EventSource,AttributeValue=cognito-idp.amazonaws.com \
    --start-time "$start_time_iso" \
    --end-time "$end_time_iso" \
    --max-items 1000 \
    --output json > "$cloudtrail_temp" || {
      echo "Warning: CloudTrail lookup failed. Check permissions or service availability." | chalk yellow
      touch "$logdir/cognito.log"  # Create empty file to prevent errors
      exit 0
    }

  # Process and filter CloudTrail events for relevant Cognito operations
  if [ -s "$cloudtrail_temp" ]; then
    # Extract events and filter for authentication-related operations
    jq -c '.Events[] | select(.EventName | test("InitiateAuth|SignUp|AdminCreateUser|RespondToAuthChallenge|AdminInitiateAuth|ConfirmSignUp|ForgotPassword|ConfirmForgotPassword|GetUser|AdminGetUser"))' "$cloudtrail_temp" >> "$logdir/cognito.log" 2>/dev/null || {
      echo "Warning: No matching Cognito events found or JSON parsing failed" | chalk yellow
      touch "$logdir/cognito.log"
    }

    # Get event count for logging
    event_count=$(jq '.Events | length' "$cloudtrail_temp" 2>/dev/null || echo "0")
    filtered_count=$(wc -l < "$logdir/cognito.log" 2>/dev/null || echo "0")

    echo "CloudTrail: Found $event_count total Cognito events, filtered to $filtered_count authentication events" | chalk green
  else
    echo "No CloudTrail events found for the specified time period" | chalk yellow
    touch "$logdir/cognito.log"
  fi

  # Cleanup temporary file
  rm -f "$cloudtrail_temp"

else
  echo "Warning: No EXPERIMENT_START_TIME set, skipping Cognito log collection" | chalk yellow
  touch "$logdir/cognito.log"
fi

# Try to collect Cognito User Pool logs if they exist
# Note: User Pool logs are not always enabled by default
user_pool_id="${COGNITO_USER_POOL_ID:-}"
if [ ! -z "$user_pool_id" ]; then
  echo "Attempting to collect Cognito User Pool logs for pool: $user_pool_id" | chalk cyan

  # Check if CloudWatch log group exists for this User Pool
  log_group_name="/aws/cognito/userpools/$user_pool_id"

  if aws logs describe-log-groups --log-group-name-prefix "$log_group_name" --query 'logGroups[0].logGroupName' --output text 2>/dev/null | grep -q "$log_group_name"; then
    echo "Found User Pool log group: $log_group_name" | chalk green

    # Collect User Pool logs with timestamp filtering (similar to aws.sh)
    if [ ! -z "${EXPERIMENT_START_TIME:-}" ]; then
      start_time_ms="${EXPERIMENT_START_TIME}"
      end_time_ms="${EXPERIMENT_END_TIME:-$(date +%s)000}"
      timestamp_params="--start-time $start_time_ms --end-time $end_time_ms"
    else
      timestamp_params=""
    fi

    for ls in $(aws logs describe-log-streams --log-group-name "$log_group_name" --query 'logStreams[].logStreamName' --output text 2>/dev/null || echo ""); do
      if [ ! -z "$ls" ]; then
        echo "|--> Collecting User Pool logs from stream: $ls" | chalk cyan
        aws logs get-log-events --log-group-name "$log_group_name" --log-stream-name "$ls" --start-from-head $timestamp_params --limit 10000 --output json 2>/dev/null | \
          jq -c '.events[]' >> "$logdir/cognito_userpool.log" 2>/dev/null || true
      fi
    done
  else
    echo "No User Pool CloudWatch logs found (this is normal if not enabled)" | chalk blue
  fi
fi

echo "Cognito log collection completed" | chalk green