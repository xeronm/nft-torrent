#!/bin/bash

# Usage: ./dbshrink.sh https://your-etcd-endpoint:2379

# Exit immediately if a command exits with a non-zero status
set -e

# Check if endpoint argument is provided
if [ -z "$1" ]; then
  echo "Usage: $0 <etcd-endpoint>"
  exit 1
fi

# Assign the endpoint from the first script argument
ENDPOINTS="$1"

# TLS configuration paths
CACERT="/etc/ssl/pgcluster/ca.crt"
CERT="/etc/ssl/pgcluster/server.crt"
KEY="/etc/ssl/pgcluster/server.key"

# Build etcdctl command with TLS and endpoint
ETCDCTL="etcdctl --cacert=${CACERT} --cert=${CERT} --key=${KEY} --endpoints=${ENDPOINTS}"

# Get current revision from etcd JSON status output
REVISION=$($ETCDCTL endpoint status --write-out=json | jq -r '.[0].Status.header.revision')

if [[ -z "$REVISION" || "$REVISION" == "null" ]]; then
  echo "Failed to get current revision from etcd"
  exit 1
fi

echo "Current revision: $REVISION"

# Run compaction up to current revision
echo "Running compaction up to revision $REVISION..."
$ETCDCTL compact "$REVISION"

# Run defragmentation to reclaim disk space
echo "Running defragmentation..."
$ETCDCTL defrag

echo "Compaction and defragmentation completed successfully."