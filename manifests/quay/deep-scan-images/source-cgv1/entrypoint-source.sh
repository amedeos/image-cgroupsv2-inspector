#!/bin/bash
# Entrypoint that sources a helper library
SCRIPT_DIR=$(dirname "$0")
source "${SCRIPT_DIR}/cgroup-helpers.sh"

echo "Memory: $(get_memory_limit)"
echo "CPU: $(get_cpu_quota)"

exec "$@"
