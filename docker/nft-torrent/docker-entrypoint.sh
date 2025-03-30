#!/bin/bash
set -e

echo "ENVIRONMENT:"
printenv

echo "Run CMD: $@"
exec $@