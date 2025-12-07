#!/bin/bash

set -euo pipefail

export AWS_DEFAULT_REGION=${AWS_REGION:-us-east-1}
echo "Getting AWS logs for deployment: ${BEFAAS_DEPLOYMENT_ID}" | chalk magenta
echo "Using AWS region: ${AWS_DEFAULT_REGION}" | chalk blue

# Check if log groups exist
log_groups=$(aws logs describe-log-groups --log-group-name-prefix /aws/${BEFAAS_DEPLOYMENT_ID} | jq -r '.logGroups[].logGroupName')
if [ -z "$log_groups" ]; then
    echo "Warning: No CloudWatch log groups found with prefix /aws/${BEFAAS_DEPLOYMENT_ID}" | chalk yellow
    echo "Available log groups:" | chalk yellow
    aws logs describe-log-groups --limit 10 | jq -r '.logGroups[].logGroupName' | head -5 || true
    exit 0
fi

echo "Found log groups: $(echo $log_groups | wc -w | tr -d ' ')" | chalk green

for lg in $log_groups; do
  echo "Getting logs for $lg" | chalk magenta
  for ls in $(aws logs describe-log-streams --log-group-name $lg | jq -r '.logStreams[].logStreamName'); do
      echo "|--> $ls" | chalk magenta
        aws logs get-log-events --log-group-name $lg --log-stream-name $ls | jq -c '.events[]' >> $logdir/aws.log
  done
done

for lg in $(aws logs describe-log-groups --log-group-name-prefix /aws/${BEFAAS_DEPLOYMENT_ID} | jq -r '.logGroups[].logGroupName'); do
  echo "Getting logs for log group $lg" | chalk magenta
  for ls in $(aws logs describe-log-streams --log-group-name $lg | jq -r '.logStreams[].logStreamName'); do
      echo "|--> Get Logs for log stream $ls" | chalk magenta
      newtoken="null"
	  end=0
      while [ $end -eq 0 ]
      do        
        if [ $newtoken == "null" ]; then
          echo "no token found, start new chain" | chalk green
          aws logs get-log-events --log-group-name $lg --log-stream-name $ls --start-from-head --limit 10000 | tee >(jq -c '.events[]' >> $logdir/aws.log) >(jq -c '.nextForwardToken' >> $logdir/token.txt) 1>/dev/null
		  #Parse next token
		  newtoken=$(tail -n 1 $logdir/token.txt | cut -d "\"" -f 2)
        else		
          echo "token already exists, using $newtoken" | chalk red
		  token=$newtoken
          aws logs get-log-events --log-group-name $lg --log-stream-name $ls --start-from-head --next-token $token  --limit 10000 | tee >(jq -c '.events[]' >> $logdir/aws.log) >(jq -c '.nextForwardToken' >> $logdir/token.txt) 1>/dev/null
          #Parse next token
          newtoken=$(tail -n 1 $logdir/token.txt | cut -d "\"" -f 2)
		  # if (newtoken == token) => no new next token => end
		  if [ $newtoken == $token ]; then
            end=1
			echo "no token update, end chain here." | chalk red
          fi
        fi  
      done
      
      echo "GetLogs complete for log stream $ls" | chalk magenta
	  #clear token.txt for next stream
	  rm $logdir/token.txt
  done
  echo "GetLogs complete for group $lg" | chalk magenta
done