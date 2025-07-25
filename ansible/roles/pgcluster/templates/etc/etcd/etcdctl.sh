#!/bin/sh

etcdctl --cacert=/etc/ssl/pgcluster/ca.crt \
  --cert=/etc/ssl/pgcluster/server.crt \
  --key=/etc/ssl/pgcluster/server.key \
  --endpoints=https://{{ ansible_host }}:2379 $@
