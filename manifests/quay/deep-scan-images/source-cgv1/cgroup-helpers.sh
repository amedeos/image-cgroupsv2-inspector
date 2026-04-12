#!/bin/bash
# Helper library for cgroup resource detection
get_memory_limit() {
    local limit
    limit=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null)
    if [[ -z "$limit" ]] || [[ "$limit" -eq 9223372036854771712 ]]; then
        echo "unlimited"
    else
        echo "$limit"
    fi
}

get_cpu_quota() {
    local quota period
    quota=$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || echo "-1")
    period=$(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us 2>/dev/null || echo "100000")
    echo "${quota}/${period}"
}

get_cpuacct_usage() {
    cat /sys/fs/cgroup/cpuacct/cpuacct.usage 2>/dev/null || echo "0"
}

get_blkio_weight() {
    cat /sys/fs/cgroup/blkio/blkio.weight 2>/dev/null || echo "500"
}
