# image-cgroupsv2-inspector

[![GitHub](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/amedeos/image-cgroupsv2-inspector)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

A tool to inspect container images in an OpenShift cluster for cgroups v2 compatibility.

This tool connects to an OpenShift cluster, collects information about all container images running in pods, deployments, statefulsets, daemonsets, jobs, and cronjobs, and saves the information to a CSV file.

## Features

- 🔌 Connect to OpenShift cluster via API URL and bearer token
- 🔑 Automatically download and save cluster pull-secret to `.pull-secret`
- 📦 Collect container images from:
  - Pods
  - Deployments
  - StatefulSets
  - DaemonSets
  - Jobs
  - CronJobs
  - ReplicaSets
- 💾 Save results to CSV with cluster name and timestamp
- 🔐 Store credentials in `.env` file for reuse
- 📁 Create rootfs directory with proper extended ACLs
- ✅ System checks: verify podman installation and disk space (min 20GB)

## ⚠️ Disclaimer

> **Warning**: This software is provided **"AS-IS"** without any warranties or guarantees of any kind. No QA or formal testing process has been performed.
>
> By using this tool, you acknowledge that:
> - You are solely responsible for verifying and validating its functionality
> - You should **test it in a non-production environment first** before using it on production clusters
> - The authors are not liable for any damages or issues arising from its use

## ⚠️ Important Prerequisites

> **Warning**: This tool requires the following conditions to work properly:
>
> 1. **Registry Accessibility**: All container registries used by the cluster must be accessible from the host running `image-cgroupsv2-inspector`. Ensure there are no network restrictions, firewalls, or VPN requirements blocking access to the registries.
>
> 2. **Pull Secret Configuration**: The cluster's pull-secret (downloaded automatically or provided via `--pull-secret`) must contain valid credentials for all registries that host the container images you want to analyze. If credentials are missing or invalid, the tool will fail to pull and analyze those images. You can also provide your own pull-secret file in podman-compatible format (JSON with `auths` structure) using the `--pull-secret` option.

## Requirements

### System Requirements

- **Python 3.12+**
  ```bash
  # RHEL 9.x / Rocky Linux 9 / AlmaLinux 9
  sudo dnf install python3.12
  
  # Fedora 39+
  sudo dnf install python3.12
  
  # Ubuntu 24.04+
  sudo apt install python3.12 python3.12-venv
  
  # Ubuntu 22.04 / Debian 12 (via deadsnakes PPA for Ubuntu)
  sudo add-apt-repository ppa:deadsnakes/ppa
  sudo apt update
  sudo apt install python3.12 python3.12-venv
  
  # Gentoo
  sudo emerge dev-lang/python:3.12
  
  # macOS (via Homebrew)
  brew install python@3.12
  ```
- **podman** - Container runtime for image inspection
  ```bash
  # Fedora/RHEL/CentOS
  sudo dnf install podman
  
  # Ubuntu/Debian
  sudo apt install podman
  
  # Gentoo
  sudo emerge app-containers/podman
  ```
- **acl** package - For extended ACL support on rootfs
  ```bash
  # Fedora/RHEL/CentOS
  sudo dnf install acl
  
  # Ubuntu/Debian
  sudo apt install acl
  
  # Gentoo
  sudo emerge sys-apps/acl
  ```

### Cluster Requirements

- Access to an OpenShift cluster with a valid token
- (Optional) cluster-admin permissions to download pull-secret

### Disk Space Requirements

- **Minimum 20GB of free disk space** on the filesystem where `--rootfs-path` is located
- This space is required for extracting and inspecting container images

## Installation

1. Clone the repository:

```bash
git clone https://github.com/amedeos/image-cgroupsv2-inspector.git
cd image-cgroupsv2-inspector
```

2. Create and activate a Python virtual environment:

```bash
python3.12 -m venv venv
source venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

```bash
# Connect with API URL and token
./image-cgroupsv2-inspector --api-url https://api.mycluster.example.com:6443 --token <token>

# Use credentials from .env file (after first connection)
./image-cgroupsv2-inspector

# Specify rootfs path for image extraction
./image-cgroupsv2-inspector --rootfs-path /tmp/images

# Analyze images for Java/NodeJS/.NET cgroup v2 compatibility
./image-cgroupsv2-inspector --rootfs-path /tmp/images --analyze

# Inspect only a specific namespace
./image-cgroupsv2-inspector -n my-namespace
./image-cgroupsv2-inspector --namespace my-namespace --analyze --rootfs-path /tmp/images
```

### Getting OpenShift Credentials

```bash
# Get your token
oc whoami -t

# Get the API URL
oc whoami --show-server
```

### Command Line Options

| Option | Description |
|--------|-------------|
| `--api-url` | OpenShift API URL (e.g., `https://api.mycluster.example.com:6443`) |
| `--token` | Bearer token for OpenShift authentication |
| `-n, --namespace` | Only inspect images in the specified namespace. If not provided, all namespaces are inspected |
| `--rootfs-path` | Path where rootfs directory will be created |
| `--output-dir` | Directory to save CSV output (default: `output`) |
| `--env-file` | Path to .env file for credentials (default: `.env`) |
| `--verify-ssl` | Verify SSL certificates (default: False) |
| `--skip-collection` | Skip image collection (useful for testing rootfs setup) |
| `--analyze` | Analyze images for Java/NodeJS/.NET binaries (requires `--rootfs-path`) |
| `--pull-secret` | Path to pull-secret file for authentication (default: `.pull-secret`) |
| `--exclude-namespaces` | Comma-separated list of namespace patterns to exclude (default: `openshift-*,kube-*`). Supports glob patterns with `*`. Ignored when `--namespace` is specified |
| `--log-to-file` | Enable logging to file |
| `--log-file` | Path to log file (default: `image-cgroupsv2-inspector.log`). Implies `--log-to-file` |
| `-v, --verbose` | Enable verbose output |
| `--version` | Show version number |

### Environment Variables

You can also set credentials via environment variables or `.env` file:

```bash
OPENSHIFT_API_URL=https://api.mycluster.example.com:6443
OPENSHIFT_TOKEN=sha256~xxxxx
```

### Single Namespace Inspection

You can limit the image inspection to a specific namespace using the `-n` or `--namespace` option:

```bash
# Inspect only the 'my-app' namespace
./image-cgroupsv2-inspector -n my-app

# Analyze images in a specific namespace
./image-cgroupsv2-inspector --namespace my-app --rootfs-path /tmp/images --analyze

# With verbose output
./image-cgroupsv2-inspector -n production-apps --analyze --rootfs-path /tmp/images -v
```

When `--namespace` is specified:
- Only resources in that namespace are inspected
- The `--exclude-namespaces` option is ignored
- The tool uses namespace-specific API calls (more efficient for large clusters)

### Namespace Exclusion

By default, infrastructure namespaces matching `openshift-*` and `kube-*` patterns are excluded from image collection. You can customize this behavior with the `--exclude-namespaces` option:

```bash
# Use default exclusion (openshift-*, kube-*)
./image-cgroupsv2-inspector --api-url URL --token TOKEN

# Exclude only openshift namespaces
./image-cgroupsv2-inspector --api-url URL --token TOKEN --exclude-namespaces "openshift-*"

# Exclude custom namespaces
./image-cgroupsv2-inspector --api-url URL --token TOKEN --exclude-namespaces "openshift-*,kube-*,test-*,dev-*"

# Include all namespaces (no exclusion)
./image-cgroupsv2-inspector --api-url URL --token TOKEN --exclude-namespaces ""
```

The exclusion patterns support glob-style wildcards:
- `*` matches any sequence of characters
- `openshift-*` matches `openshift-etcd`, `openshift-monitoring`, etc.
- `*-test` matches `app-test`, `service-test`, etc.

## Image Analysis for cgroup v2 Compatibility

When using the `--analyze` flag, the tool:

1. Pulls each unique container image using podman
2. Exports the container filesystem to a temporary directory
3. Searches for Java, Node.js, and .NET binaries
4. Executes `-version` / `--version` to determine the exact version
5. Checks if the version is compatible with cgroup v2
6. Cleans up the image and filesystem after each analysis

### cgroup v2 Minimum Versions

| Runtime | Minimum Compatible Version |
|---------|---------------------------|
| OpenJDK / HotSpot | 8u372, 11.0.16, 15+ |
| IBM Semeru Runtimes | 8u345-b01, 11.0.16.0, 17.0.4.0, 18.0.2.0+ |
| IBM SDK Java (IBM Java) | 8.0.7.15+ |
| Node.js | 20.3.0+ |
| .NET | 5.0+ |

### Analysis Example

```bash
./image-cgroupsv2-inspector --rootfs-path /tmp/analysis --analyze

# Output includes:
#   🔬 Analysis Results:
#      Java found in: 45 containers
#        ✓ cgroup v2 compatible: 30
#        ✗ cgroup v2 incompatible: 15
#      Node.js found in: 12 containers
#        ✓ cgroup v2 compatible: 10
#        ✗ cgroup v2 incompatible: 2
#      .NET found in: 8 containers
#        ✓ cgroup v2 compatible: 6
#        ✗ cgroup v2 incompatible: 2
```

## Output

The tool generates a CSV file in the `output` directory with the following columns:

| Column | Description |
|--------|-------------|
| `container_name` | Name of the container |
| `namespace` | Kubernetes namespace |
| `object_type` | Type of object (Pod, Deployment, StatefulSet, etc.) |
| `object_name` | Name of the parent object |
| `image_name` | Full image name with tag |
| `image_id` | Full image ID (when available) |
| `java_binary` | Path to Java binary found (or "None") |
| `java_version` | Java version detected |
| `java_cgroup_v2_compatible` | "Yes", "No", or "N/A" |
| `node_binary` | Path to Node.js binary found (or "None") |
| `node_version` | Node.js version detected |
| `node_cgroup_v2_compatible` | "Yes", "No", or "N/A" |
| `dotnet_binary` | Path to .NET binary found (or "None") |
| `dotnet_version` | .NET version detected |
| `dotnet_cgroup_v2_compatible` | "Yes", "No", or "N/A" |
| `analysis_error` | Error message if analysis failed |

### Identifying Incompatible Images

The fields that indicate cgroups v2 incompatibility are:

- **`java_cgroup_v2_compatible`**: If set to **"No"**, the Java runtime in the image is NOT compatible with cgroup v2
- **`node_cgroup_v2_compatible`**: If set to **"No"**, the Node.js runtime in the image is NOT compatible with cgroup v2
- **`dotnet_cgroup_v2_compatible`**: If set to **"No"**, the .NET runtime in the image is NOT compatible with cgroup v2

Possible values for these fields:
- `Yes` - The runtime is compatible with cgroup v2
- `No` - The runtime is **NOT** compatible with cgroup v2 and requires an upgrade
- `N/A` - The runtime was not found in the image

Example filename: `mycluster-20241222-143052.csv`

## RootFS Directory

When using `--rootfs-path`, the tool:

1. **Validates the filesystem:**
   - Checks write permissions
   - Verifies at least 20GB of free disk space
   - Confirms extended ACL support

2. **Creates a `rootfs` directory with:**
   - rwx permissions for the current user and group
   - SGID bit set (new files inherit the group)
   - Extended ACLs for the current user and group
   - Default ACLs (inherited by new files/directories):
     - `d:u:<user>:rwx` - Default user ACL
     - `d:g:<group>:rwx` - Default group ACL
     - `d:m::rwx` - Default mask
     - `d:o::---` - No access for others

This setup ensures the user can create, modify, and delete files in the rootfs directory.

## Test Resources

The `test/` directory contains sample Kubernetes manifests to test the cgroups v2 compatibility detection on a real OpenShift cluster.

### Test Files

| File | Description |
|------|-------------|
| `namespace-java.yaml` | Namespace `test-java` for Java test deployments |
| `namespace-node.yaml` | Namespace `test-node` for Node.js test deployments |
| `namespace-dotnet.yaml` | Namespace `test-dotnet` for .NET test deployments |
| `deployment-java-compatible.yaml` | Deployment with OpenJDK 17 (cgroups v2 compatible) |
| `deployment-java-incompatible.yaml` | Deployment with OpenJDK 8u362 (cgroups v2 **incompatible**) |
| `deployment-node-compatible.yaml` | Deployment with Node.js 20 (cgroups v2 compatible) |
| `deployment-node-incompatible.yaml` | Deployment with Node.js 18 (cgroups v2 **incompatible**) |
| `deployment-dotnet-compatible.yaml` | Deployment with .NET 8.0 (cgroups v2 compatible) |
| `deployment-dotnet-incompatible.yaml` | Deployment with .NET Core 3.0 (cgroups v2 **incompatible**) |

### Deploying Test Resources

```bash
# Deploy Java test resources
oc apply -f test/namespace-java.yaml
oc apply -f test/deployment-java-compatible.yaml
oc apply -f test/deployment-java-incompatible.yaml

# Deploy Node.js test resources
oc apply -f test/namespace-node.yaml
oc apply -f test/deployment-node-compatible.yaml
oc apply -f test/deployment-node-incompatible.yaml

# Deploy .NET test resources
oc apply -f test/namespace-dotnet.yaml
oc apply -f test/deployment-dotnet-compatible.yaml
oc apply -f test/deployment-dotnet-incompatible.yaml

# Verify pods are running
oc get pods -n test-java
oc get pods -n test-node
oc get pods -n test-dotnet
```

### Running Analysis on Test Resources

```bash
# Analyze only the test namespaces
./image-cgroupsv2-inspector \
  --api-url <URL> \
  --token <TOKEN> \
  --rootfs-path /tmp/rootfs \
  --exclude-namespaces "openshift-*,kube-*" \
  --analyze \
  -v
```

### Cleanup

```bash
oc delete namespace test-java test-node test-dotnet
```

## Project Structure

```
image-cgroupsv2-inspector/
├── image-cgroupsv2-inspector  # Main executable
├── requirements.txt           # Python dependencies
├── README.md                  # This file
├── LICENSE                    # License file
├── .gitignore                # Git ignore rules
├── .env                      # Credentials (not in git)
├── .pull-secret              # Cluster pull secret (not in git)
├── output/                   # CSV output directory (not in git)
│   └── <cluster>-<datetime>.csv
├── src/
│   ├── __init__.py
│   ├── openshift_client.py   # OpenShift connection handling
│   ├── image_collector.py    # Image collection logic
│   ├── image_analyzer.py     # Image analysis for cgroups v2
│   ├── rootfs_manager.py     # RootFS directory management
│   └── system_checks.py      # System requirements verification
└── test/                     # Test Kubernetes manifests
    ├── namespace-java.yaml
    ├── namespace-node.yaml
    ├── namespace-dotnet.yaml
    ├── deployment-java-compatible.yaml
    ├── deployment-java-incompatible.yaml
    ├── deployment-node-compatible.yaml
    ├── deployment-node-incompatible.yaml
    ├── deployment-dotnet-compatible.yaml
    └── deployment-dotnet-incompatible.yaml
```

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests on the [GitHub repository](https://github.com/amedeos/image-cgroupsv2-inspector).

## License

This project is licensed under the GPL-3.0 License - see the [LICENSE](LICENSE) file for details.

