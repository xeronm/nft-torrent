#!/bin/bash
set -e

echo "ENVIRONMENT:"
printenv

if [ -d /etc/entrypoint.d ]; then
    for script in /etc/entrypoint.d/*.sh
    do
        if [ -x ${script} ]; then
            echo "Run entrypoint.d script: ${script}"
            "${script}"
        fi;
    done
fi

echo "Run CMD: $@"
exec $@