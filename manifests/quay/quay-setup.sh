#!/bin/bash
###############################################################################
# quay-setup.sh — Populate a Quay registry with test images for cgroups v2
#                 compatibility testing.
#
# Part of the image-cgroupsv2-inspector project (issue #28, epic #21).
# This is the Quay equivalent of the OpenShift manifests in manifests/cluster/.
#
# Prerequisites:
#   - podman (for pulling, tagging, and pushing images)
#   - curl   (for Quay API calls)
#
# Usage:
#   # Self-hosted Quay with self-signed cert (OAuth token)
#   ./manifests/quay/quay-setup.sh \
#     --registry-url https://quay.lab.example.com \
#     --token <your-oauth-token> \
#     --tls-verify false
#
#   # Self-hosted Quay with robot account
#   ./manifests/quay/quay-setup.sh \
#     --registry-url https://quay.lab.example.com \
#     --org myorg \
#     --username "myorg+robot" \
#     --token <robot-token> \
#     --tls-verify false
#
#   # quay.io
#   ./manifests/quay/quay-setup.sh \
#     --registry-url https://quay.io \
#     --org my-test-org \
#     --token <your-oauth-token>
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
DATE_TAG=$(date +%Y%m%d)

PUSH_SUCCESS=0
PUSH_FAIL=0
FAILED_IMAGES=()
MAX_RETRIES=3
RETRY_DELAY=5

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Populate a Quay registry with test container images for cgroups v2
compatibility testing.

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

  $(basename "$0") \\
    --registry-url https://quay.io \\
    --org my-test-org --token my-token
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

curl_opts() {
    local opts=(-s -o /dev/null -w "%{http_code}")
    if [[ "$TLS_VERIFY" == "false" ]]; then
        opts+=(-k)
    fi
    echo "${opts[@]}"
}

# ---------------------------------------------------------------------------
# Quay API: verify the organization exists
# ---------------------------------------------------------------------------
check_organization() {
    info "Checking that Quay organization '${ORG}' exists ..."

    local curl_tls=()
    if [[ "$TLS_VERIFY" == "false" ]]; then
        curl_tls=(-k)
    fi

    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        "${curl_tls[@]}" \
        -H "Authorization: Bearer ${TOKEN}" \
        "${REGISTRY_URL}/api/v1/organization/${ORG}")

    case "$http_code" in
        200)
            success "Organization '${ORG}' found."
            ;;
        404)
            error "Organization '${ORG}' does not exist. Please create it in Quay before running this script."
            exit 1
            ;;
        *)
            error "Unable to verify organization '${ORG}' (HTTP ${http_code}). Check your --registry-url and --token."
            exit 1
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Podman login
# ---------------------------------------------------------------------------
podman_login() {
    local host
    host=$(registry_host)
    info "Logging in to ${host} with podman ..."

    local login_user="${USERNAME:-\$oauthtoken}"
    info "  username: ${login_user}"

    if podman login "$host" \
        --username="$login_user" \
        --password="$TOKEN" \
        --tls-verify="$TLS_VERIFY" 2>&1; then
        success "Podman login to ${host} succeeded."
    else
        error "Podman login to ${host} failed."
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Pull → Tag → Push
# ---------------------------------------------------------------------------
pull_tag_push() {
    local upstream="$1"
    local repo="$2"
    local tag="$3"

    local host
    host=$(registry_host)
    local target="${host}/${ORG}/${repo}:${tag}"

    info "Processing ${target}"

    # Pull
    info "  Pulling ${upstream} ..."
    if ! podman pull "$upstream" --tls-verify="$TLS_VERIFY" 2>&1; then
        error "  Failed to pull ${upstream}"
        PUSH_FAIL=$((PUSH_FAIL + 1))
        FAILED_IMAGES+=("${target} (pull failed)")
        return 1
    fi

    # Tag
    info "  Tagging as ${target} ..."
    if ! podman tag "$upstream" "$target" 2>&1; then
        error "  Failed to tag ${upstream} -> ${target}"
        PUSH_FAIL=$((PUSH_FAIL + 1))
        FAILED_IMAGES+=("${target} (tag failed)")
        return 1
    fi

    # Push (with retry)
    local attempt
    for attempt in $(seq 1 "$MAX_RETRIES"); do
        info "  Pushing ${target} (attempt ${attempt}/${MAX_RETRIES}) ..."
        if podman push "$target" --tls-verify="$TLS_VERIFY" 2>&1; then
            success "  Pushed ${target}"
            PUSH_SUCCESS=$((PUSH_SUCCESS + 1))
            return 0
        fi
        if [[ $attempt -lt $MAX_RETRIES ]]; then
            warn "  Push failed, retrying in ${RETRY_DELAY}s ..."
            sleep "$RETRY_DELAY"
        fi
    done

    error "  Failed to push ${target} after ${MAX_RETRIES} attempts"
    PUSH_FAIL=$((PUSH_FAIL + 1))
    FAILED_IMAGES+=("${target} (push failed)")
    return 1
}

# Push an additional tag for an image already pulled.
# Reuses the local image from a previous pull_tag_push call.
add_tag() {
    local source_repo="$1"
    local source_tag="$2"
    local new_tag="$3"

    local host
    host=$(registry_host)
    local source="${host}/${ORG}/${source_repo}:${source_tag}"
    local target="${host}/${ORG}/${source_repo}:${new_tag}"

    info "Adding extra tag ${target}"

    if ! podman tag "$source" "$target" 2>&1; then
        error "  Failed to tag ${source} -> ${target}"
        PUSH_FAIL=$((PUSH_FAIL + 1))
        FAILED_IMAGES+=("${target} (tag failed)")
        return 1
    fi

    local attempt
    for attempt in $(seq 1 "$MAX_RETRIES"); do
        info "  Pushing ${target} (attempt ${attempt}/${MAX_RETRIES}) ..."
        if podman push "$target" --tls-verify="$TLS_VERIFY" 2>&1; then
            success "  Pushed ${target}"
            PUSH_SUCCESS=$((PUSH_SUCCESS + 1))
            return 0
        fi
        if [[ $attempt -lt $MAX_RETRIES ]]; then
            warn "  Push failed, retrying in ${RETRY_DELAY}s ..."
            sleep "$RETRY_DELAY"
        fi
    done

    error "  Failed to push ${target} after ${MAX_RETRIES} attempts"
    PUSH_FAIL=$((PUSH_FAIL + 1))
    FAILED_IMAGES+=("${target} (push failed)")
    return 1
}

# ---------------------------------------------------------------------------
# Push all test images
# ---------------------------------------------------------------------------
push_test_images() {
    info "Pushing test images (date tag: ${DATE_TAG}) ..."
    echo ""

    # --- Java compatible (OpenJDK 17) ---
    info "=== Java compatible (OpenJDK 17) ==="
    pull_tag_push "registry.access.redhat.com/ubi8/openjdk-17:latest" \
        "java-compatible" "17" || true
    add_tag "java-compatible" "17" "17-${DATE_TAG}" || true
    add_tag "java-compatible" "17" "latest" || true
    add_tag "java-compatible" "17" "dev" || true
    echo ""

    # --- Java incompatible (OpenJDK 8) ---
    info "=== Java incompatible (OpenJDK 8u362) ==="
    pull_tag_push "registry.access.redhat.com/ubi8/openjdk-8:1.14" \
        "java-incompatible" "8u362" || true
    add_tag "java-incompatible" "8u362" "8u362-${DATE_TAG}" || true
    add_tag "java-incompatible" "8u362" "latest" || true
    echo ""

    # --- Node.js compatible (Node 20) ---
    info "=== Node.js compatible (Node 20) ==="
    pull_tag_push "docker.io/library/node:20-slim" \
        "node-compatible" "20" || true
    add_tag "node-compatible" "20" "20-${DATE_TAG}" || true
    add_tag "node-compatible" "20" "latest" || true
    add_tag "node-compatible" "20" "dev" || true
    echo ""

    # --- Node.js incompatible (Node 18) ---
    info "=== Node.js incompatible (Node 18) ==="
    pull_tag_push "docker.io/library/node:18-slim" \
        "node-incompatible" "18" || true
    add_tag "node-incompatible" "18" "18-${DATE_TAG}" || true
    add_tag "node-incompatible" "18" "latest" || true
    echo ""

    # --- .NET compatible (.NET 8.0) ---
    info "=== .NET compatible (.NET 8.0) ==="
    pull_tag_push "mcr.microsoft.com/dotnet/runtime:8.0" \
        "dotnet-compatible" "8.0" || true
    add_tag "dotnet-compatible" "8.0" "8.0-${DATE_TAG}" || true
    add_tag "dotnet-compatible" "8.0" "latest" || true
    echo ""

    # --- .NET incompatible (.NET Core 3.0) ---
    info "=== .NET incompatible (.NET Core 3.0) ==="
    pull_tag_push "mcr.microsoft.com/dotnet/core/runtime:3.0" \
        "dotnet-incompatible" "3.0" || true
    add_tag "dotnet-incompatible" "3.0" "3.0-${DATE_TAG}" || true
    add_tag "dotnet-incompatible" "3.0" "latest" || true
    echo ""

    # --- No runtime (UBI 9 minimal) ---
    info "=== No runtime (UBI 9 minimal) ==="
    pull_tag_push "registry.access.redhat.com/ubi9-minimal:latest" \
        "no-runtime" "latest" || true
    add_tag "no-runtime" "latest" "9-${DATE_TAG}" || true
    echo ""
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print_summary() {
    echo ""
    info "============================================"
    info "  Setup complete"
    info "============================================"
    success "Images pushed successfully: ${PUSH_SUCCESS}"
    if [[ $PUSH_FAIL -gt 0 ]]; then
        error "Images failed: ${PUSH_FAIL}"
        for img in "${FAILED_IMAGES[@]}"; do
            error "  - ${img}"
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
    info "  Quay test environment setup"
    info "============================================"
    echo ""

    validate_args
    check_prerequisites
    check_organization
    podman_login
    push_test_images
    print_summary

    if [[ $PUSH_FAIL -gt 0 ]]; then
        exit 1
    fi
}

main
