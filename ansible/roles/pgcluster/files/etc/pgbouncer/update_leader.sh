#!/usr/bin/bash
set -euo pipefail

CALLBACK="$1"
ROLE="$2"
CLUSTER_ID="$3"

logger -t patroni-callback "$CALLBACK: PostgreSQL role changed to: $ROLE, cluster: $CLUSTER_ID"

PATRONI_CONFIG="/etc/patroni/patroni.yaml"
PGBOUNCER_CONFIG="/etc/pgbouncer/pgbouncer.ini"
TEMP_CONFIG="/tmp/pgbouncer.ini.tmp"
BACKUP_CONFIG="/etc/pgbouncer/pgbouncer.ini.bak"

# Query current Leader
LEADER_IP=$(patronictl -c $PATRONI_CONFIG list --format json | \
            jq -r '.[] | select(.Role=="Leader") | .Host')

[ -z "$LEADER_IP" ] && {
  logger -t patroni-callback "ERROR: Leader not found"
  echo "ERROR: Leader not found"; exit 1;
}

# Create updated config
awk -v ip="$LEADER_IP" '
  /^\[databases\]/ { in_databases=1 }
  in_databases && /^postgres =/ {
    sub(/host=[^ ]+/, "host=" ip); in_databases=0
  }
  { print }
' $PGBOUNCER_CONFIG > $TEMP_CONFIG

# Apply changes
mv $TEMP_CONFIG $PGBOUNCER_CONFIG
if [ -r /var/run/pgbouncer/pgbouncer.pid ]; then
  kill -HUP "$(cat /var/run/pgbouncer/pgbouncer.pid)"
fi

logger -t patroni-callback "Updated PgBouncer to point to leader: $LEADER_IP"
