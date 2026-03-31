#!/bin/bash
###############################################################################
# quay-teardown.sh — Remove all test resources created by quay-setup.sh.
#
# Part of the image-cgroupsv2-inspector project (issue #28, epic #21).
# Deletes Quay test repositories and cleans up local podman images.
# The organization itself is never deleted.
#
# Prerequisites:
#   - curl   (for Quay API calls)
#   - podman (for local image cleanup)
#
# Usage:
#   # Remove repos only (OAuth token)
#   ./manifests/quay/quay-teardown.sh \
#     --registry-url https://quay.lab.example.com \
#     --token <your-oauth-token> \
#     --tls-verify false
#
#   # Remove repos with robot account
#   ./manifests/quay/quay-teardown.sh \
#     --registry-url https://quay.lab.example.com \
#     --username "myorg+robot" \
#     --token <robot-token> \
#     --tls-verify false
#
###############################################################################
set -euo pipefail

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
REGISTRY_URL=""
ORG="test-cgroupsv2"
USERNAME=""
TOKEN=""
TLS_VERIFY="true"

DELETE_SUCCESS=0
DELETE_FAIL=0
FAILED_REPOS=()

TEST_REPOS=(
    java-compatible
    java-incompatible
    node-compatible
    node-incompatible
    dotnet-compatible
    dotnet-incompatible
    no-runtime
)

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Remove all test resources created by quay-setup.sh.

Required:
  --registry-url URL   Quay instance URL (e.g. https://quay.example.com)
  --token TOKEN        Quay OAuth or robot account token

Optional:
  --org NAME           Quay organization (default: test-cgroupsv2)
  --username USER      Registry login username (default: \$oauthtoken).
                       Use org+robotname for robot accounts.
  --tls-verify BOOL    Verify TLS certificates (default: true)
  --help               Show this help message

Examples:
  $(basename "$0") \\
    --registry-url https://quay.lab.example.com \\
    --token my-token --tls-verify false

  $(basename "$0") \\
    --registry-url https://quay.lab.example.com \\
    --username "myorg+robot" --token robot-token --tls-verify false
EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --registry-url) REGISTRY_URL="$2"; shift 2 ;;
        --org)          ORG="$2";          shift 2 ;;
        --username)     USERNAME="$2";     shift 2 ;;
        --token)        TOKEN="$2";        shift 2 ;;
        --tls-verify)   TLS_VERIFY="$2";   shift 2 ;;
        --help)         usage ;;
        *)
            error "Unknown option: $1"
            usage
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
check_prerequisites() {
    local missing=0
    for cmd in podman curl; do
        if ! command -v "$cmd" &>/dev/null; then
            error "'$cmd' is required but not found in PATH."
            missing=1
        fi
    done
    if [[ $missing -ne 0 ]]; then
        exit 1
    fi
    success "Prerequisites satisfied (podman, curl)."
}

validate_args() {
    if [[ -z "$REGISTRY_URL" ]]; then
        error "--registry-url is required."
        usage
    fi
    if [[ -z "$TOKEN" ]]; then
        error "--token is required."
        usage
    fi
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
registry_host() {
    echo "$REGISTRY_URL" | sed -E 's|^https?://||' | sed 's|/.*||'
}

# ---------------------------------------------------------------------------
# Delete a single repository via Quay API
# ---------------------------------------------------------------------------
delete_repository() {
    local repo="$1"

    local curl_tls=()
    if [[ "$TLS_VERIFY" == "false" ]]; then
        curl_tls=(-k)
    fi

    info "Deleting repository ${ORG}/${repo} ..."

    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        "${curl_tls[@]}" \
        -X DELETE \
        -H "Authorization: Bearer ${TOKEN}" \
        "${REGISTRY_URL}/api/v1/repository/${ORG}/${repo}")

    case "$http_code" in
        200|204)
            success "  Deleted ${ORG}/${repo}."
            DELETE_SUCCESS=$((DELETE_SUCCESS + 1))
            ;;
        404)
            warn "  Repository ${ORG}/${repo} not found (HTTP 404). Skipping."
            ;;
        *)
            error "  Failed to delete ${ORG}/${repo} (HTTP ${http_code})."
            DELETE_FAIL=$((DELETE_FAIL + 1))
            FAILED_REPOS+=("${repo}")
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Delete all test repositories
# ---------------------------------------------------------------------------
delete_all_repositories() {
    info "Deleting test repositories from organization '${ORG}' ..."
    echo ""

    for repo in "${TEST_REPOS[@]}"; do
        delete_repository "$repo"
    done
    echo ""
}

# ---------------------------------------------------------------------------
# Clean up local podman images
# ---------------------------------------------------------------------------
cleanup_local_images() {
    local host
    host=$(registry_host)

    info "Cleaning up local podman images for ${ORG}@${host} ..."

    for repo in "${TEST_REPOS[@]}"; do
        local images
        images=$(podman images --format "{{.Repository}}:{{.Tag}}" \
            | grep "^${host}/${ORG}/${repo}:" 2>/dev/null || true)

        if [[ -n "$images" ]]; then
            while IFS= read -r img; do
                info "  Removing local image ${img} ..."
                podman rmi "$img" 2>/dev/null || warn "  Could not remove ${img}"
            done <<< "$images"
        fi
    done

    # Also clean up the upstream images that were pulled
    local upstream_images=(
        "registry.access.redhat.com/ubi8/openjdk-17:latest"
        "registry.access.redhat.com/ubi8/openjdk-8:1.14"
        "docker.io/library/node:20-slim"
        "docker.io/library/node:18-slim"
        "mcr.microsoft.com/dotnet/runtime:8.0"
        "mcr.microsoft.com/dotnet/core/runtime:3.0"
        "registry.access.redhat.com/ubi9-minimal:latest"
    )

    info "Cleaning up upstream images ..."
    for img in "${upstream_images[@]}"; do
        if podman image exists "$img" 2>/dev/null; then
            info "  Removing ${img} ..."
            podman rmi "$img" 2>/dev/null || warn "  Could not remove ${img}"
        fi
    done

    success "Local image cleanup complete."
    echo ""
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print_summary() {
    echo ""
    info "============================================"
    info "  Teardown complete"
    info "============================================"
    success "Repositories deleted: ${DELETE_SUCCESS}"
    if [[ $DELETE_FAIL -gt 0 ]]; then
        error "Repositories failed to delete: ${DELETE_FAIL}"
        for repo in "${FAILED_REPOS[@]}"; do
            error "  - ${repo}"
        done
    else
        success "No failures."
    fi
    info "Organization: ${ORG}"
    info "Registry:     $(registry_host)"
    echo ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    echo ""
    info "============================================"
    info "  Quay test environment teardown"
    info "============================================"
    echo ""

    validate_args
    check_prerequisites
    delete_all_repositories
    cleanup_local_images
    print_summary

    if [[ $DELETE_FAIL -gt 0 ]]; then
        exit 1
    fi
}

main
