# image-cgroupsv2-inspector

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

## Requirements

### System Requirements

- **Python 3.12+**
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
git clone <repository-url>
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
| `--rootfs-path` | Path where rootfs directory will be created |
| `--output-dir` | Directory to save CSV output (default: `output`) |
| `--env-file` | Path to .env file for credentials (default: `.env`) |
| `--verify-ssl` | Verify SSL certificates (default: False) |
| `--skip-collection` | Skip image collection (useful for testing rootfs setup) |
| `-v, --verbose` | Enable verbose output |
| `--version` | Show version number |

### Environment Variables

You can also set credentials via environment variables or `.env` file:

```bash
OPENSHIFT_API_URL=https://api.mycluster.example.com:6443
OPENSHIFT_TOKEN=sha256~xxxxx
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
└── src/
    ├── __init__.py
    ├── openshift_client.py   # OpenShift connection handling
    ├── image_collector.py    # Image collection logic
    ├── rootfs_manager.py     # RootFS directory management
    └── system_checks.py      # System requirements verification
```

## License

See the [LICENSE](LICENSE) file for details.

