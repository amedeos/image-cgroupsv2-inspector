#!/bin/bash
# This entrypoint reads cgroup v1 paths for memory tuning
MEM_LIMIT=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || echo "0")
CPU_QUOTA=$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || echo "-1")
CPU_PERIOD=$(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us 2>/dev/null || echo "100000")
CPU_SHARES=$(cat /sys/fs/cgroup/cpu/cpu.shares 2>/dev/null || echo "1024")

echo "Memory limit: ${MEM_LIMIT}"
echo "CPU quota: ${CPU_QUOTA}/${CPU_PERIOD}"
echo "CPU shares: ${CPU_SHARES}"

exec "$@"
