package main

import (
	"fmt"
	"os"
	"strings"
)

const (
	cgroupV1MemoryLimit = "/sys/fs/cgroup/memory/memory.limit_in_bytes"
	cgroupV1MemoryUsage = "/sys/fs/cgroup/memory/memory.usage_in_bytes"
	cgroupV1CPUQuota    = "/sys/fs/cgroup/cpu/cpu.cfs_quota_us"
	cgroupV1CPUPeriod   = "/sys/fs/cgroup/cpu/cpu.cfs_period_us"
	cgroupV1CPUShares   = "/sys/fs/cgroup/cpu/cpu.shares"
	cgroupV1CPUAcct     = "/sys/fs/cgroup/cpuacct/cpuacct.usage"
)

func readCgroupFile(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return "unavailable"
	}
	return strings.TrimSpace(string(data))
}

func main() {
	fmt.Printf("Memory limit: %s\n", readCgroupFile(cgroupV1MemoryLimit))
	fmt.Printf("Memory usage: %s\n", readCgroupFile(cgroupV1MemoryUsage))
	fmt.Printf("CPU quota: %s\n", readCgroupFile(cgroupV1CPUQuota))
	fmt.Printf("CPU period: %s\n", readCgroupFile(cgroupV1CPUPeriod))
	fmt.Printf("CPU shares: %s\n", readCgroupFile(cgroupV1CPUShares))
	fmt.Printf("CPU accounting: %s\n", readCgroupFile(cgroupV1CPUAcct))
}
