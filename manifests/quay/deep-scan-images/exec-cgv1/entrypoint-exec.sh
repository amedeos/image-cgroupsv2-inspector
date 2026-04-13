#!/bin/bash
# Wrapper entrypoint that does setup then exec's the actual application.
# This script intentionally has NO cgroup v1 references.
# The deep-scan should follow the exec chain and scan the binary.

echo "Initializing application..."
echo "Environment: $(hostname)"

exec /usr/local/bin/cgroup-reader "$@"
