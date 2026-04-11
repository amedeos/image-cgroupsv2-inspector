# image-cgroupsv2-inspector

[![GitHub](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/amedeos/image-cgroupsv2-inspector)
[![CI](https://github.com/amedeos/image-cgroupsv2-inspector/actions/workflows/ci.yml/badge.svg)](https://github.com/amedeos/image-cgroupsv2-inspector/actions/workflows/ci.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/downloads/release/python-3120/)

A tool to inspect container images for cgroups v2 compatibility. Supports scanning images from OpenShift clusters and Quay registries.

This tool connects to an OpenShift cluster or a Quay registry, collects information about container images, and saves the information to a CSV file. In OpenShift mode it discovers images from running workloads (pods, deployments, statefulsets, daemonsets, jobs, and cronjobs). In registry mode it enumerates repositories and tags in a Quay organization via the REST API.

## Features

- 🔌 Connect to OpenShift cluster via API URL and bearer token
- 🏭 Connect to Quay registry via API URL and Application Token
- 🔑 Automatically download and save cluster pull-secret to `.pull-secret` (skipped if the file already exists)
- 🔑 Automatic auth.json generation from Quay token for podman pulls
- 📦 Collect container images from:
  - Pods
  - Deployments
  - DeploymentConfigs (OpenShift)
  - StatefulSets
  - DaemonSets
  - Jobs
  - CronJobs
  - ReplicaSets
- 📦 Collect container images from Quay organizations and repositories
- 🏷️ Filter images by tag patterns (include/exclude globs, latest-only)
- 💾 Save results to CSV with cluster name or registry host and timestamp
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

### OpenShift Mode Prerequisites

> 1. **Registry Accessibility**: All container registries used by the cluster must be accessible from the host running `image-cgroupsv2-inspector`. Ensure there are no network restrictions, firewalls, or VPN requirements blocking access to the registries.
>
>    **OpenShift Internal Registry**: Images hosted in the OpenShift internal registry (`image-registry.openshift-image-registry.svc:5000/...`) are also supported. The tool automatically detects these images and rewrites the pull URL to use the registry's external route. By default, the tool auto-detects the `default-route` in the `openshift-image-registry` namespace. If your cluster uses a **custom route** instead of the default one, you can specify it with `--internal-registry-route`:
>    ```bash
>    # Auto-detect (uses default-route)
>    ./image-cgroupsv2-inspector --analyze --rootfs-path /tmp/images
>
>    # Custom route
>    ./image-cgroupsv2-inspector --analyze --rootfs-path /tmp/images \
>      --internal-registry-route my-registry-openshift-image-registry.apps.example.com
>    ```
>    For auto-detection to work, the internal registry default-route must be exposed:
>    ```bash
>    oc patch configs.imageregistry.operator.openshift.io/cluster --type merge -p '{"spec":{"defaultRoute":true}}'
>    ```
>    The token used to connect to the cluster is also used to authenticate against the internal registry route. Note that `--tls-verify=false` is used automatically for these pulls, as the route typically uses a self-signed certificate.
>
> 2. **Pull Secret Configuration**: The cluster's pull-secret must contain valid credentials for all registries that host the container images you want to analyze. If credentials are missing or invalid, the tool will fail to pull and analyze those images. You can provide your own pull-secret file in podman-compatible format (JSON with `auths` structure) using the `--pull-secret` option. If the pull-secret file already exists at the specified path (default: `.pull-secret`), the tool will use it as-is and **will not** download the cluster pull-secret, avoiding accidental overwrites. The automatic download from the cluster only happens when the file does not exist yet.

### Registry Mode Prerequisites

> 1. **Network Access**: The Quay registry must be accessible from the host running `image-cgroupsv2-inspector`. Ensure there are no network restrictions, firewalls, or VPN requirements blocking access to the registry.
>
> 2. **Quay Authentication**: A Quay **Application Token** (OAuth token) is required. The token must be created with the following permissions:
>    - **View all visible repositories**
>    - **Read User Information**
>
>    The token is used both for REST API access and for generating an `auth.json` file for podman pulls.
>
>    To create the token: Quay UI → Organization → Applications → Create New Application → Generate Token, then select the two permissions listed above.
>
>    **Note:** Robot accounts are **not** supported for the registry scan mode, as the tool requires Quay REST API access (organization and repository listing) which is only available with Application Tokens.
>
> 3. **podman**: Required for pulling and analyzing container images (same as OpenShift mode).

## Comparison: OpenShift vs Registry Mode

| Feature | OpenShift mode | Registry mode |
|---------|----------------|---------------|
| Data source | Running workloads (Pods, Deployments, etc.) | Quay registry API (repos and tags) |
| Authentication | OpenShift bearer token (`oc whoami -t`) | Quay Application Token (OAuth token) |
| Image discovery | Cluster API queries | Quay REST API |
| Image analysis | Same (podman pull + binary scan) | Same (podman pull + binary scan) |
| Use case | Post-deployment audit | Pre-deployment assessment / registry hygiene |
| Pull secret | Cluster pull-secret or custom | Auto-generated from token or custom |

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
- Use `--skip-disk-check` to bypass this check (a warning will be logged instead of stopping execution)

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

## Container

You can build and run the tool as a container (UBI 9, Python 3.12). The image uses the main script as the entrypoint.

**Build:**

```bash
podman build -t image-cgroupsv2-inspector -f Containerfile .
# or: docker build -t image-cgroupsv2-inspector -f Containerfile .
```

**Run (OpenShift mode):**

Mount output and, for `--analyze`, a writable rootfs path. Optionally mount `.env` and `.pull-secret` if you use them.

```bash
# With API URL and token
podman run --rm -v ./output:/app/output \
  image-cgroupsv2-inspector --api-url https://api.mycluster.example.com:6443 --token <token>

# Using .env (mount it into the container)
podman run --rm -v ./.env:/app/.env -v ./output:/app/output \
  image-cgroupsv2-inspector

# With analysis (mount rootfs path and optionally pull-secret)
podman run --rm \
  -v ./.env:/app/.env \
  -v ./.pull-secret:/app/.pull-secret \
  -v ./output:/app/output \
  -v /tmp/rootfs:/tmp/rootfs \
  image-cgroupsv2-inspector --rootfs-path /tmp/rootfs --analyze
```

**Run (Registry mode):**

```bash
podman run --rm \
  -v ./output:/app/output \
  -v /tmp/rootfs:/tmp/rootfs \
  image-cgroupsv2-inspector \
  --registry-url https://quay.io \
  --registry-token <token> \
  --registry-org myorg \
  --rootfs-path /tmp/rootfs \
  --analyze
```

The container runs as root. For image pulls and analysis, podman runs inside the container; you may need appropriate capabilities or privileges (e.g. `--privileged` or volume mounts for `/var/lib/containers`) depending on your environment.

## Usage

### OpenShift Mode

#### Basic Usage

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

# Limit each image pull+scan to 120 seconds (default: 600)
./image-cgroupsv2-inspector --rootfs-path /tmp/images --analyze --image-timeout 120
```

#### Getting OpenShift Credentials

```bash
# Get your token
oc whoami -t

# Get the API URL
oc whoami --show-server
```

#### Single Namespace Inspection

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

#### Namespace Exclusion

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

### Registry Scan Mode

#### Basic Usage

```bash
# Scan all repos in an org
./image-cgroupsv2-inspector \
  --registry-url https://quay.example.com \
  --registry-token <token> \
  --registry-org myorg

# Scan and analyze images
./image-cgroupsv2-inspector \
  --registry-url https://quay.example.com \
  --registry-token <token> \
  --registry-org myorg \
  --rootfs-path /tmp/images \
  --analyze

# Scan a specific repository
./image-cgroupsv2-inspector \
  --registry-url https://quay.example.com \
  --registry-token <token> \
  --registry-org myorg \
  --registry-repo myapp \
  --rootfs-path /tmp/images \
  --analyze
```

#### Getting Quay Credentials

A Quay **Application Token** (OAuth token) is required. Robot accounts are **not** supported.

Create the token via: **Quay UI → Organization → Applications → Create New Application → Generate Token**

Select the following permissions when generating the token:
- **View all visible repositories**
- **Read User Information**

#### Tag Filtering

```bash
# Include only tags matching patterns
./image-cgroupsv2-inspector \
  --registry-url https://quay.example.com \
  --registry-token <token> \
  --registry-org myorg \
  --include-tags "v*,release-*"

# Exclude dev/snapshot tags
./image-cgroupsv2-inspector \
  --registry-url https://quay.example.com \
  --registry-token <token> \
  --registry-org myorg \
  --exclude-tags "*-dev,*-snapshot,*-rc*"

# Only scan the 3 most recent tags per repo
./image-cgroupsv2-inspector \
  --registry-url https://quay.example.com \
  --registry-token <token> \
  --registry-org myorg \
  --latest-only 3

# Combine filters
./image-cgroupsv2-inspector \
  --registry-url https://quay.example.com \
  --registry-token <token> \
  --registry-org myorg \
  --exclude-tags "*-dev,latest" \
  --latest-only 5 \
  --rootfs-path /tmp/images \
  --analyze
```

Tag filtering processing order:
1. Include patterns (keep matching, default: `*`)
2. Exclude patterns (remove matching)
3. Sort by date (most recent first)
4. Apply latest-only limit

#### Environment Variables

```bash
QUAY_REGISTRY_URL=https://quay.example.com
QUAY_REGISTRY_TOKEN=<token>
QUAY_REGISTRY_ORG=myorg
```

These can also be set in the `.env` file. CLI arguments override environment variables.

### Resuming Interrupted Scans

On large clusters or registries with thousands of images, scans can take hours. If a scan is interrupted (e.g., network failure, killed process), the `--resume` flag lets you restart where you left off instead of re-scanning all images from the beginning.

A JSON state file is written automatically during every `--analyze` run, tracking which images have been processed. The state file is stored in the output directory (or the directory specified by `--state-dir`).

```bash
# First run — interrupted after scanning 2000 of 4900 images
./image-cgroupsv2-inspector --rootfs-path /tmp/images --analyze

# Resume — skips the 2000 already-scanned images, scans remaining 2900
./image-cgroupsv2-inspector --rootfs-path /tmp/images --analyze --resume

# Store state files in a custom directory
./image-cgroupsv2-inspector --rootfs-path /tmp/images --analyze --resume --state-dir /var/tmp/scan-state

# Clean up the state file when done (or to force a fresh scan)
./image-cgroupsv2-inspector --clean-state

# Clean up by target name (no cluster/registry connection needed)
./image-cgroupsv2-inspector --clean-state ocp-prod

# Registry mode works the same way
./image-cgroupsv2-inspector \
  --registry-url https://quay.example.com \
  --registry-token <token> \
  --registry-org myorg \
  --rootfs-path /tmp/images \
  --analyze --resume
```

**State file details:**

- Named `.state_<target>.json` (e.g., `.state_ocp-prod.json` or `.state_quay.example.com.json`)
- Written after each image is processed, using atomic writes to prevent corruption
- Contains a list of completed image names and timestamps
- If `--resume` is used without a prior state file, a warning is printed and a full scan starts
- Images that time out or fail are also marked as completed to avoid retrying them indefinitely
- `--clean-state` deletes the state file and exits immediately (code `0`). Pass a target name (e.g. `--clean-state ocp-prod`) to skip the cluster/registry connection

### Command Line Options

**OpenShift mode options:**

| Option | Description |
|--------|-------------|
| `--api-url` | OpenShift API URL (e.g., `https://api.mycluster.example.com:6443`) |
| `--token` | Bearer token for OpenShift authentication |
| `-n, --namespace` | Only inspect images in the specified namespace. If not provided, all namespaces are inspected (except those excluded by `--exclude-namespaces`) |
| `--exclude-namespaces` | Comma-separated list of namespace patterns to exclude. Supports glob patterns with `*` (default: `openshift-*,kube-*`). Ignored when `--namespace` is specified |
| `--internal-registry-route` | Custom hostname for the OpenShift internal registry route. When not specified, the tool auto-detects the `default-route` from the cluster |

**Registry mode options:**

| Option | Description |
|--------|-------------|
| `--registry-url` | Quay registry URL (e.g., `https://quay.example.com`). Activates registry scan mode |
| `--registry-token` | Quay Application Token (OAuth token) for authentication. Required permissions: "View all visible repositories" + "Read User Information" |
| `--registry-org` | Quay organization to scan (required in registry mode) |
| `--registry-repo` | Specific Quay repository to scan (optional, scans all repos if omitted) |
| `--include-tags` | Comma-separated glob patterns for tags to include (e.g., `"v*,release-*"`) |
| `--exclude-tags` | Comma-separated glob patterns for tags to exclude (e.g., `"*-dev,*-snapshot"`) |
| `--latest-only` | Only scan the N most recent tags per repository |

**Shared options:**

| Option | Description |
|--------|-------------|
| `--rootfs-path` | Path where rootfs directory will be created for image extraction |
| `--output-dir` | Directory to save CSV output (default: `output`) |
| `--analyze` | Analyze images for Java/NodeJS/.NET binaries (requires `--rootfs-path`) |
| `--pull-secret` | Path to pull-secret file for image authentication (default: `.pull-secret`) |
| `--verify-ssl` | Verify SSL certificates (default: False) |
| `--env-file` | Path to .env file for credentials (default: `.env`) |
| `--skip-collection` | Skip image collection (useful for testing rootfs setup) |
| `--skip-disk-check` | Skip the 20GB minimum free disk space check. A warning will be logged instead of stopping execution |
| `--image-timeout` | Maximum seconds for pulling and scanning each individual image (default: `600`). If an image exceeds this limit it is skipped with a warning and the tool exits with code `2` |
| `--resume` | Resume an interrupted scan by skipping images that were already scanned in a previous run. Reads progress from a JSON state file |
| `--clean-state [TARGET]` | Delete the state file and exit with code `0`. When a target name is given (e.g. `--clean-state ocp-prod`), no cluster/registry connection is needed |
| `--state-dir` | Directory where state files are stored (default: same as `--output-dir`) |
| `--log-to-file` | Enable logging to file |
| `--log-file` | Path to log file (default: `image-cgroupsv2-inspector.log`). Implies `--log-to-file` |
| `-v, --verbose` | Enable verbose output |
| `--version` | Show version number |

### Environment Variables

You can also set credentials via environment variables or `.env` file:

```bash
# OpenShift mode
OPENSHIFT_API_URL=https://api.mycluster.example.com:6443
OPENSHIFT_TOKEN=sha256~xxxxx

# Registry mode
QUAY_REGISTRY_URL=https://quay.example.com
QUAY_REGISTRY_TOKEN=<token>
QUAY_REGISTRY_ORG=myorg
```

## Short-Name Image Resolution

Container images can be specified using short-names (e.g., `eclipse-temurin:17`) or fully qualified domain names (FQDN, e.g., `docker.io/library/eclipse-temurin:17`). When a pod is scheduled, the kubelet asks the container runtime (CRI-O) to pull the image. For short-name images, CRI-O tries the registries listed in `unqualified-search-registries` from its `registries.conf` until the pull succeeds. The FQDN of the image that was actually pulled is then recorded in the pod's `status.containerStatuses[*].image` field.

### How it Works

The tool automatically resolves short-name images to their FQDN by reading the resolved image from pod status:

| Resource Type | Resolution Method |
|---------------|-------------------|
| Pod | Uses `status.containerStatuses[*].image` directly |
| Deployment | Finds pods via label selector, gets resolved image from pod status |
| DeploymentConfig | Finds pods via label selector, gets resolved image from pod status |
| StatefulSet | Finds pods via label selector, gets resolved image from pod status |
| DaemonSet | Finds pods via label selector, gets resolved image from pod status |
| ReplicaSet | Finds pods via label selector, gets resolved image from pod status |
| Job | Finds pods via `job-name` label, gets resolved image from pod status |
| CronJob | Uses spec image directly (pods may not exist) |

### Why This Matters

If your local host doesn't have the same registry search configuration as the cluster (e.g., `unqualified-search-registries` in `registries.conf`), podman won't be able to pull short-name images. By resolving to FQDN first, the tool ensures images can be pulled and analyzed regardless of local registry configuration.

### Limitations

- **DeploymentConfig**: DeploymentConfigs are an OpenShift-specific API (`apps.openshift.io`). If the cluster does not have this API (e.g. vanilla Kubernetes), the tool skips DeploymentConfigs and continues without error.
- **CronJobs**: Since CronJob pods are transient (created when scheduled, then cleaned up), the tool uses the spec image directly. If the CronJob uses a short-name image, it may fail to pull during analysis unless your local registry configuration can resolve it.
- **Pods not running**: If a controller's pods are not running (e.g., scaled to 0, failed, pending), the resolved image cannot be obtained and the spec image is used.

## Image Analysis for cgroup v2 Compatibility

When using the `--analyze` flag, the tool:

1. Detects the OpenShift internal registry default-route (if exposed) — OpenShift mode only
2. Pulls each unique container image using podman (rewriting internal registry URLs when needed)
3. Exports the container filesystem to a temporary directory
4. Searches for Java, Node.js, and .NET binaries
5. Executes `-version` / `--version` to determine the exact version
6. Checks if the version is compatible with cgroup v2
7. Cleans up the image and filesystem after each analysis

### Internal Registry Support

Images that reference the cluster-internal registry service address (`image-registry.openshift-image-registry.svc:5000/...`) cannot be pulled directly from outside the cluster. When the tool detects such images, it automatically:

1. Determines the external route for the internal registry:
   - If `--internal-registry-route` is specified, that hostname is used directly
   - Otherwise, queries the cluster for the `default-route` in `openshift-image-registry`
2. Rewrites the image URL to use the external route for pulling
3. Uses `--tls-verify=false` for the pull (the route typically uses a self-signed certificate)

**Using a custom registry route:**

Some clusters expose the internal registry through a custom route rather than the default one. In that case, use `--internal-registry-route`:

```bash
./image-cgroupsv2-inspector --analyze --rootfs-path /tmp/images \
  --internal-registry-route my-registry-openshift-image-registry.apps.example.com
```

**Using auto-detection (default-route):**

To enable auto-detection, ensure the internal registry default-route is exposed:

```bash
oc patch configs.imageregistry.operator.openshift.io/cluster --type merge -p '{"spec":{"defaultRoute":true}}'
```

Or apply the provided YAML:

```bash
oc apply -f manifests/cluster/registry-default-route.yaml
```

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
#        ✗ cgroup v2 incompatible: 12
#        ? cgroup v2 unknown: 3
#      Node.js found in: 12 containers
#        ✓ cgroup v2 compatible: 10
#        ✗ cgroup v2 incompatible: 2
#      .NET found in: 8 containers
#        ✓ cgroup v2 compatible: 6
#        ✗ cgroup v2 incompatible: 2
```

## Output

The tool generates a CSV file in the `output` directory (or the path specified by `--output-dir`).

### CSV Columns (unified schema)

| Column | Description |
|--------|-------------|
| `source` | `"openshift"` or `"registry"` — identifies the scan mode (NEW in v2.0) |
| `container_name` | Name of the container (OpenShift only) |
| `namespace` | Kubernetes namespace (OpenShift only) |
| `object_type` | Type of object — Pod, Deployment, DeploymentConfig, StatefulSet, etc. (OpenShift only) |
| `object_name` | Name of the parent object (OpenShift only) |
| `registry_org` | Quay organization name (Registry only, NEW in v2.0) |
| `registry_repo` | Quay repository name (Registry only, NEW in v2.0) |
| `image_name` | Full image name with tag (both modes) |
| `image_id` | Full image ID when available (both modes) |
| `java_binary` | Path to Java binary found (or "None") |
| `java_version` | Java version detected |
| `java_cgroup_v2_compatible` | "Yes", "No", "Unknown", or "N/A" |
| `node_binary` | Path to Node.js binary found (or "None") |
| `node_version` | Node.js version detected |
| `node_cgroup_v2_compatible` | "Yes", "No", "Unknown", or "N/A" |
| `dotnet_binary` | Path to .NET binary found (or "None") |
| `dotnet_version` | .NET version detected |
| `dotnet_cgroup_v2_compatible` | "Yes", "No", "Unknown", or "N/A" |
| `analysis_error` | Error message if analysis failed |

### Identifying Incompatible Images

The fields that indicate cgroups v2 incompatibility are:

- **`java_cgroup_v2_compatible`**: If set to **"No"**, the Java runtime in the image is NOT compatible with cgroup v2
- **`node_cgroup_v2_compatible`**: If set to **"No"**, the Node.js runtime in the image is NOT compatible with cgroup v2
- **`dotnet_cgroup_v2_compatible`**: If set to **"No"**, the .NET runtime in the image is NOT compatible with cgroup v2

Possible values for these fields:
- `Yes` - The runtime is compatible with cgroup v2
- `No` - The runtime is **NOT** compatible with cgroup v2 and requires an upgrade
- `Unknown` - The runtime was found but its version could not be determined (e.g. the binary failed to execute inside the container)
- `N/A` - The runtime was not found in the image

### Filename Format

- **OpenShift mode**: `{cluster_name}-{YYYYMMDD}-{HHMMSS}.csv`
- **Registry mode**: `{registry_host}-{org}-{YYYYMMDD}-{HHMMSS}.csv`

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

### OpenShift Cluster

The `manifests/cluster/` directory contains sample Kubernetes manifests to test the cgroups v2 compatibility detection on a real OpenShift cluster.

#### Test Files

| File | Description |
|------|-------------|
| `namespace-java.yaml` | Namespace `test-java` for Java test deployments |
| `namespace-java-short.yaml` | Namespace `test-java-short` for Java test deployments with short-name images |
| `namespace-node.yaml` | Namespace `test-node` for Node.js test deployments |
| `namespace-dotnet.yaml` | Namespace `test-dotnet` for .NET test deployments |
| `deployment-java-compatible.yaml` | Deployment with OpenJDK 17 (cgroups v2 compatible) |
| `deployment-java-incompatible.yaml` | Deployment with OpenJDK 8u362 (cgroups v2 **incompatible**) |
| `deployment-java-short-compatible.yaml` | Deployment with Eclipse Temurin 17 using short-name image (cgroups v2 compatible) |
| `deployment-java-short-incompatible.yaml` | Deployment with Eclipse Temurin 8 using short-name image (cgroups v2 **incompatible**) |
| `deployment-node-compatible.yaml` | Deployment with Node.js 20 (cgroups v2 compatible) |
| `deployment-node-incompatible.yaml` | Deployment with Node.js 18 (cgroups v2 **incompatible**) |
| `deployment-dotnet-compatible.yaml` | Deployment with .NET 8.0 (cgroups v2 compatible) |
| `deployment-dotnet-incompatible.yaml` | Deployment with .NET Core 3.0 (cgroups v2 **incompatible**) |
| `namespace-java-dc.yaml` | Namespace `test-java-dc` for DeploymentConfig tests |
| `deploymentconfig-java-compatible.yaml` | DeploymentConfig with OpenJDK 17 (cgroups v2 compatible) |
| `deploymentconfig-java-incompatible.yaml` | DeploymentConfig with OpenJDK 8u362 (cgroups v2 **incompatible**) |
| `namespace-java-intreg.yaml` | Namespace `test-java-internalreg` for internal registry test deployments |
| `registry-default-route.yaml` | Enable default route on the OpenShift internal image registry |
| `imagestream-java-intreg-compatible.yaml` | ImageStream importing `ubi8/openjdk-17:latest` into the internal registry |
| `imagestream-java-intreg-incompatible.yaml` | ImageStream importing `ubi8/openjdk-8:1.14` into the internal registry |
| `deployment-java-intreg-compatible.yaml` | Deployment with OpenJDK 17 from internal registry (cgroups v2 compatible) |
| `deployment-java-intreg-incompatible.yaml` | Deployment with OpenJDK 8 from internal registry (cgroups v2 **incompatible**) |

#### Deploying Test Resources

```bash
# Deploy Java test resources (FQDN images)
oc apply -f manifests/cluster/namespace-java.yaml
oc apply -f manifests/cluster/deployment-java-compatible.yaml
oc apply -f manifests/cluster/deployment-java-incompatible.yaml

# Deploy Java test resources (short-name images)
oc apply -f manifests/cluster/namespace-java-short.yaml
oc apply -f manifests/cluster/deployment-java-short-compatible.yaml
oc apply -f manifests/cluster/deployment-java-short-incompatible.yaml

# Deploy Node.js test resources
oc apply -f manifests/cluster/namespace-node.yaml
oc apply -f manifests/cluster/deployment-node-compatible.yaml
oc apply -f manifests/cluster/deployment-node-incompatible.yaml

# Deploy .NET test resources
oc apply -f manifests/cluster/namespace-dotnet.yaml
oc apply -f manifests/cluster/deployment-dotnet-compatible.yaml
oc apply -f manifests/cluster/deployment-dotnet-incompatible.yaml

# Deploy DeploymentConfig test resources (OpenShift)
oc apply -f manifests/cluster/namespace-java-dc.yaml
oc apply -f manifests/cluster/deploymentconfig-java-compatible.yaml
oc apply -f manifests/cluster/deploymentconfig-java-incompatible.yaml

# Deploy internal registry test resources
oc apply -f manifests/cluster/registry-default-route.yaml
oc apply -f manifests/cluster/namespace-java-intreg.yaml
oc apply -f manifests/cluster/imagestream-java-intreg-compatible.yaml
oc apply -f manifests/cluster/imagestream-java-intreg-incompatible.yaml
oc apply -f manifests/cluster/deployment-java-intreg-compatible.yaml
oc apply -f manifests/cluster/deployment-java-intreg-incompatible.yaml

# Verify pods are running
oc get pods -n test-java
oc get pods -n test-java-short
oc get pods -n test-node
oc get pods -n test-dotnet
oc get pods -n test-java-dc
oc get pods -n test-java-internalreg
```

#### Running Analysis on Test Resources (OpenShift Mode)

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

#### Cleanup

```bash
oc delete namespace test-java test-java-short test-node test-dotnet test-java-dc test-java-internalreg
```

### Quay Registry Test Environment

The `manifests/quay/` directory contains shell scripts that populate a Quay registry with test container images for cgroups v2 compatibility testing. This is the registry-scan counterpart to the OpenShift manifests above.

| Script | Description |
|--------|-------------|
| `quay-setup.sh` | Verifies the Quay organization exists, then pulls upstream images and pushes them with multiple tags |
| `quay-teardown.sh` | Deletes the test repositories and cleans up local images (the organization is never deleted) |

**Prerequisites:** `podman` and `curl`. The Quay organization must already exist before running the setup script.

#### Setup

```bash
# With OAuth token
./manifests/quay/quay-setup.sh \
  --registry-url https://quay.example.com \
  --org my-test-org \
  --token <your-oauth-token>

# With robot account and self-signed cert
./manifests/quay/quay-setup.sh \
  --registry-url https://quay.example.com \
  --org my-test-org \
  --username "my-test-org+robot" \
  --token <robot-token> \
  --tls-verify false
```

#### Teardown

```bash
# Remove test repos and local images
./manifests/quay/quay-teardown.sh \
  --registry-url https://quay.example.com \
  --org my-test-org \
  --token <your-oauth-token>

# With robot account and self-signed cert
./manifests/quay/quay-teardown.sh \
  --registry-url https://quay.example.com \
  --org my-test-org \
  --username "my-test-org+robot" \
  --token <robot-token> \
  --tls-verify false
```

The setup script is idempotent and includes retry logic (3 attempts) for push operations. Run `--help` on either script for full option details.

#### Running Analysis on Test Resources (Registry Mode)

```bash
./image-cgroupsv2-inspector \
  --registry-url https://quay.example.com \
  --registry-token <token> \
  --registry-org test-cgroupsv2 \
  --rootfs-path /tmp/rootfs \
  --analyze \
  -v
```

## Project Structure

```
image-cgroupsv2-inspector/
├── image-cgroupsv2-inspector   # Main executable (Python 3.12) — v2.0.0
├── requirements.txt
├── pyproject.toml              # ruff + pytest config
├── Containerfile
├── README.md
├── LICENSE
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI
├── src/
│   ├── __init__.py
│   ├── openshift_client.py     # OpenShift REST API client
│   ├── image_collector.py      # Collects images from OpenShift workloads
│   ├── quay_client.py          # Quay REST API client (NEW in v2.0)
│   ├── registry_collector.py   # Collects images from Quay registry (NEW in v2.0)
│   ├── analysis_orchestrator.py # Source-agnostic analysis orchestration (NEW in v2.0)
│   ├── auth_utils.py           # Registry auth.json generation (NEW in v2.0)
│   ├── image_analyzer.py       # Image analysis for cgroups v2
│   ├── rootfs_manager.py       # RootFS directory management
│   └── system_checks.py        # System requirements verification
├── tests/
│   ├── __init__.py
│   ├── test_image_analyzer.py
│   ├── test_image_collector.py
│   ├── test_openshift_client.py
│   ├── test_quay_client.py           # NEW in v2.0
│   ├── test_registry_collector.py    # NEW in v2.0
│   ├── test_analysis_orchestrator.py # NEW in v2.0
│   ├── test_auth_utils.py            # NEW in v2.0
│   └── test_cli_registry.py          # NEW in v2.0
└── manifests/
    ├── cluster/                # OpenShift test manifests
    │   ├── namespace-java.yaml
    │   ├── deployment-java-compatible.yaml
    │   └── ...
    └── quay/                   # Quay test environment scripts (NEW in v2.0)
        ├── quay-setup.sh
        └── quay-teardown.sh
```

## Development

### CI Pipeline

The project uses [GitHub Actions](https://github.com/amedeos/image-cgroupsv2-inspector/actions) with three stages:

1. **Lint** — [ruff](https://docs.astral.sh/ruff/) for linting and formatting
2. **Test** — [pytest](https://docs.pytest.org/) with coverage reporting
3. **Container Build** — validates the `Containerfile` builds successfully

The CI pipeline runs on pull requests to `main` and on feature branches.

### Running Locally

```bash
# Install dev dependencies
pip install ruff pytest pytest-cov

# Lint
ruff check .
ruff format --check .

# Run tests
pytest tests/ -v

# Run tests with coverage
pytest tests/ -v --cov=src --cov-report=term-missing
```

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests on the [GitHub repository](https://github.com/amedeos/image-cgroupsv2-inspector).

## License

This project is licensed under the GPL-3.0 License - see the [LICENSE](LICENSE) file for details.
