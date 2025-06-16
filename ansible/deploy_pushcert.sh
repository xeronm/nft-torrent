#!/bin/bash

if [ -z "$BASH_VERSION" ]; then
  echo "Error: This script must be run with bash" >&2
  exit 1
fi

# Resolve the absolute path to this script
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

# Extract domain from certificate path propagated from certbot
if [ -z "$RENEWED_LINEAGE" ]; then
  echo "Error: RENEWED_LINEAGE is not set. This script must be run by certbot as a deploy-hook." >&2
  exit 1
fi

ansible-playbook ${SCRIPT_DIR}/pushcert.yaml \
  -i ${SCRIPT_DIR}/inventory \
  -e domain="$DOMAIN"
STATUS=$?

if [ $STATUS -ne 0 ]; then
  echo "Ansible playbook failed with exit code $STATUS" >&2
  exit $STATUS
fi

exit 0