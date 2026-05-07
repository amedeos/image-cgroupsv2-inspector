#!/bin/bash
###############################################################################
# jfrog-teardown.sh — Remove all test resources created by jfrog-setup.sh.
#
# Mirror of manifests/quay/quay-teardown.sh. Deletes the Docker image
# folders (and all their tags) created under the JFrog repository, then
# cleans up local podman images. The JFrog repository itself is never
# deleted.
#
# Prerequisites:
#   - curl   (for JFrog Artifactory REST API calls)
#   - podman (for local image cleanup)
#
# Usage:
#   ./manifests/jfrog/jfrog-teardown.sh \
#     --registry-url https://acme.jfrog.io \
#     --repo docker-local \
#     --token <bearer-access-token>
#
###############################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFESTS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

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
REPO="docker-local"
USERNAME=""
TOKEN=""
TLS_VERIFY="true"

DELETE_SUCCESS=0
DELETE_FAIL=0
FAILED_REPOS=()

# Source the shared catalog: brings in TEST_REPOS and UPSTREAM_TEST_IMAGES.
# shellcheck source=../test-images.sh
source "${MANIFESTS_DIR}/test-images.sh"

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Remove all test resources created by jfrog-setup.sh.

Required:
  --registry-url URL   JFrog Artifactory base URL (e.g. https://acme.jfrog.io)
  --repo KEY           JFrog Docker repository key (e.g. docker-local)
  --token TOKEN        JFrog Bearer access token

Optional:
  --username USER      Accepted for symmetry with jfrog-setup.sh (unused
                       by teardown — REST DELETE uses Bearer token only).
  --tls-verify BOOL    Verify TLS certificates (default: true)
  --help               Show this help message

Examples:
  $(basename "$0") \\
    --registry-url https://acme.jfrog.io \\
    --repo docker-local \\
    --token my-bearer-token

  $(basename "$0") \\
    --registry-url https://artifactory.lab.example.com \\
    --repo docker-local \\
    --token my-bearer-token \\
    --tls-verify false
EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --registry-url) REGISTRY_URL="$2"; shift 2 ;;
        --repo)         REPO="$2";         shift 2 ;;
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
    if [[ -z "$REPO" ]]; then
        error "--repo is required."
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
# Delete a single Docker image folder via JFrog Artifactory REST.
#   DELETE /artifactory/{repo}/{image-name}
# Removes all tags of the image in one call.
# ---------------------------------------------------------------------------
delete_repository() {
    local image="$1"

    local curl_tls=()
    if [[ "$TLS_VERIFY" == "false" ]]; then
        curl_tls=(-k)
    fi

    info "Deleting ${REPO}/${image} ..."

    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        "${curl_tls[@]}" \
        -X DELETE \
        -H "Authorization: Bearer ${TOKEN}" \
        "${REGISTRY_URL}/artifactory/${REPO}/${image}")

    case "$http_code" in
        200|204)
            success "  Deleted ${REPO}/${image}."
            DELETE_SUCCESS=$((DELETE_SUCCESS + 1))
            ;;
        404)
            warn "  ${REPO}/${image} not found (HTTP 404). Skipping."
            ;;
        401|403)
            error "  Authentication failed for ${REPO}/${image} (HTTP ${http_code}). Check your --token."
            DELETE_FAIL=$((DELETE_FAIL + 1))
            FAILED_REPOS+=("${image}")
            ;;
        *)
            error "  Failed to delete ${REPO}/${image} (HTTP ${http_code})."
            DELETE_FAIL=$((DELETE_FAIL + 1))
            FAILED_REPOS+=("${image}")
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Delete all test image folders
# ---------------------------------------------------------------------------
delete_all_repositories() {
    info "Deleting test images from JFrog repository '${REPO}' ..."
    echo ""

    for image in "${TEST_REPOS[@]}"; do
        delete_repository "$image"
    done
    echo ""
}

# ---------------------------------------------------------------------------
# Clean up local podman images
# ---------------------------------------------------------------------------
cleanup_local_images() {
    local host
    host=$(registry_host)

    info "Cleaning up local podman images for ${REPO}@${host} ..."

    for image in "${TEST_REPOS[@]}"; do
        local images
        images=$(podman images --format "{{.Repository}}:{{.Tag}}" \
            | grep "^${host}/${REPO}/${image}:" 2>/dev/null || true)

        if [[ -n "$images" ]]; then
            while IFS= read -r img; do
                info "  Removing local image ${img} ..."
                podman rmi "$img" 2>/dev/null || warn "  Could not remove ${img}"
            done <<< "$images"
        fi
    done

    info "Cleaning up upstream images ..."
    for img in "${UPSTREAM_TEST_IMAGES[@]}"; do
        if podman image exists "$img" 2>/dev/null; then
            info "  Removing ${img} ..."
            podman rmi "$img" 2>/dev/null || warn "  Could not remove ${img}"
        fi
    done

    info "Cleaning up locally built deep-scan images ..."
    local deep_scan_local
    deep_scan_local=$(podman images --format "{{.Repository}}:{{.Tag}}" \
        | grep -E "^(localhost/)?deep-scan-" 2>/dev/null || true)
    if [[ -n "$deep_scan_local" ]]; then
        while IFS= read -r img; do
            info "  Removing local build image ${img} ..."
            podman rmi "$img" 2>/dev/null || warn "  Could not remove ${img}"
        done <<< "$deep_scan_local"
    fi

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
    success "Images deleted: ${DELETE_SUCCESS}"
    if [[ $DELETE_FAIL -gt 0 ]]; then
        error "Images failed to delete: ${DELETE_FAIL}"
        for repo in "${FAILED_REPOS[@]}"; do
            error "  - ${repo}"
        done
    else
        success "No failures."
    fi
    info "Repository: ${REPO}"
    info "Registry:   $(registry_host)"
    echo ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    echo ""
    info "============================================"
    info "  JFrog test environment teardown"
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
