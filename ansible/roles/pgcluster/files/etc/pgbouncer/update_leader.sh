#!/usr/bin/bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: ./update_leader.sh <CALLBACK> [<ROLE> <CLUSTER_ID>]" >&2
  exit 1
fi

CALLBACK="$1"

if [ $# -gt 2 ]; then
  ROLE="$2"
  CLUSTER_ID="$3"
  logger -t patroni-callback "Callback - $CALLBACK: PostgreSQL role changed to: $ROLE, cluster: $CLUSTER_ID"
else
  logger -t patroni-callback "Callback - $CALLBACK"
fi;


PATRONI_CONFIG="/etc/patroni/patroni.yaml"
PGBOUNCER_CONFIG="/etc/pgbouncer/pgbouncer.ini"
TEMP_CONFIG="/tmp/pgbouncer.ini.tmp"
BACKUP_CONFIG="/etc/pgbouncer/pgbouncer.ini.bak"

# Query current Leader
LEADER_IP=$(/usr/local/bin/patronictl -c $PATRONI_CONFIG list --format json | \
            jq -r '.[] | select(.Role=="Leader") | .Host')

[ -z "$LEADER_IP" ] && {
  logger -t patroni-callback "ERROR: Leader not found"
  echo "ERROR: Leader not found"; exit 1;
}

CURRENT_IP=$(awk '
  /^\[databases\]/ { in_db=1; next }
  in_db && /^\[/ { exit }
  in_db && /^[^#].*=/ && match($0, /host=([^ ]+)/, m) { print m[1] }
' "$PGBOUNCER_CONFIG" | sort -u | head -n1)

if [[ "$CURRENT_IP" != "$LEADER_IP" ]]; then
  logger -t patroni-callback "Leader changed from $CURRENT_IP to $LEADER_IP — updating config"
else
  logger -t patroni-callback "Leader in config match to patroni leader $LEADER_IP"
  exit 0;
fi


# Create updated config
awk -v ip="$LEADER_IP" '
  /^\[databases\]/ { in_db=1 }
  in_db && /^\[/ && !/^\[databases\]/ { in_db=0 }
  in_db && /^[^#].*=/ {
    sub(/host=[^ ]+/, "host=" ip)
  }
  { print }
' "$PGBOUNCER_CONFIG" > "$TEMP_CONFIG"

# Apply changes
mv $TEMP_CONFIG $PGBOUNCER_CONFIG
if [ -r /var/run/pgbouncer/pgbouncer.pid ]; then
  kill -HUP "$(cat /var/run/pgbouncer/pgbouncer.pid)"
fi

logger -t patroni-callback "Updated PgBouncer to point to leader: $LEADER_IP"
