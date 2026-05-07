#!/bin/bash
###############################################################################
# jfrog-setup.sh — Populate a JFrog Container Registry with test images for
#                  cgroups v2 compatibility testing.
#
# Mirror of manifests/quay/quay-setup.sh for a JFrog Artifactory / JFrog
# Container Registry instance. Containerfile sources are reused from
# manifests/quay/deep-scan-images/ — only the destination differs.
#
# Prerequisites:
#   - podman (for pulling, tagging, and pushing images)
#   - curl   (for JFrog Artifactory REST API calls)
#
# Usage:
#   # JFrog Cloud (SaaS)
#   ./manifests/jfrog/jfrog-setup.sh \
#     --registry-url https://acme.jfrog.io \
#     --repo docker-local \
#     --username my.user@acme.com \
#     --token <bearer-access-token>
#
#   # Self-hosted JFrog with self-signed cert
#   ./manifests/jfrog/jfrog-setup.sh \
#     --registry-url https://artifactory.lab.example.com \
#     --repo docker-local \
#     --username admin \
#     --token <bearer-access-token> \
#     --tls-verify false
#
###############################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFESTS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Containerfile contexts are shared with the Quay setup.
CONTAINERFILES_DIR="${MANIFESTS_DIR}/quay/deep-scan-images"

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

Populate a JFrog Container Registry with test container images for
cgroups v2 compatibility testing.

Required:
  --registry-url URL   JFrog Artifactory base URL (e.g. https://acme.jfrog.io)
  --repo KEY           JFrog Docker repository key (e.g. docker-local)
  --username USER      Username for podman login (typically the JFrog user
                       associated with the access token)
  --token TOKEN        JFrog Bearer access token

Optional:
  --tls-verify BOOL    Verify TLS certificates (default: true)
  --help               Show this help message

Examples:
  $(basename "$0") \\
    --registry-url https://acme.jfrog.io \\
    --repo docker-local \\
    --username my.user@acme.com \\
    --token my-bearer-token

  $(basename "$0") \\
    --registry-url https://artifactory.lab.example.com \\
    --repo docker-local \\
    --username admin \\
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
    if [[ -z "$USERNAME" ]]; then
        error "--username is required."
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
# JFrog API: verify the repository exists and the token is valid.
#   GET /artifactory/api/repositories?type=local
# Lists local repositories and greps for the requested key. This endpoint
# works on Artifactory Community Edition; the per-repo configuration
# endpoint (/api/repositories/{repo}) is Pro-only and returns HTTP 400
# on CE.
# ---------------------------------------------------------------------------
check_repository() {
    info "Checking that JFrog repository '${REPO}' exists ..."

    local curl_tls=()
    if [[ "$TLS_VERIFY" == "false" ]]; then
        curl_tls=(-k)
    fi

    local response status body
    response=$(curl -s -w $'\n%{http_code}' \
        "${curl_tls[@]}" \
        -H "Authorization: Bearer ${TOKEN}" \
        "${REGISTRY_URL}/artifactory/api/repositories?type=local")
    status="${response##*$'\n'}"
    body="${response%$'\n'*}"

    case "$status" in
        200)
            if echo "$body" | grep -Eq "\"key\"[[:space:]]*:[[:space:]]*\"${REPO}\""; then
                success "Repository '${REPO}' found."
                return 0
            fi
            error "Repository '${REPO}' was not returned by /api/repositories?type=local."
            error "Create it in JFrog Artifactory before running this script (kind: Local, package type: Docker)."
            exit 1
            ;;
        401|403)
            error "Authentication failed (HTTP ${status}). Check your --token."
            [[ -n "$body" ]] && error "  Server response: ${body}"
            exit 1
            ;;
        *)
            error "Unable to list JFrog repositories (HTTP ${status})."
            [[ -n "$body" ]] && error "  Server response: ${body}"
            error "Check --registry-url and --token (and --tls-verify if using a self-signed cert)."
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
    info "  username: ${USERNAME}"

    if podman login "$host" \
        --username="$USERNAME" \
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
    local target="${host}/${REPO}/${repo}:${tag}"

    info "Processing ${target}"

    info "  Pulling ${upstream} ..."
    if ! podman pull "$upstream" --tls-verify="$TLS_VERIFY" 2>&1; then
        error "  Failed to pull ${upstream}"
        PUSH_FAIL=$((PUSH_FAIL + 1))
        FAILED_IMAGES+=("${target} (pull failed)")
        return 1
    fi

    info "  Tagging as ${target} ..."
    if ! podman tag "$upstream" "$target" 2>&1; then
        error "  Failed to tag ${upstream} -> ${target}"
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

# Push an additional tag for an image already pulled.
add_tag() {
    local source_repo="$1"
    local source_tag="$2"
    local new_tag="$3"

    local host
    host=$(registry_host)
    local source="${host}/${REPO}/${source_repo}:${source_tag}"
    local target="${host}/${REPO}/${source_repo}:${new_tag}"

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
# Build → Tag → Push (for custom Containerfile-based images)
# ---------------------------------------------------------------------------
build_and_push() {
    local context_dir="$1"
    local containerfile_name="$2"
    local repo="$3"
    local tag="$4"

    local host
    host=$(registry_host)
    local local_image="${repo}:${tag}"
    local target="${host}/${REPO}/${repo}:${tag}"

    info "Processing ${target} (build from ${context_dir}/${containerfile_name})"

    info "  Building ${local_image} ..."
    if ! podman build \
        -t "$local_image" \
        -f "${context_dir}/${containerfile_name}" \
        --tls-verify="$TLS_VERIFY" \
        "$context_dir" 2>&1; then
        error "  Failed to build ${local_image}"
        PUSH_FAIL=$((PUSH_FAIL + 1))
        FAILED_IMAGES+=("${target} (build failed)")
        return 1
    fi

    info "  Tagging as ${target} ..."
    if ! podman tag "$local_image" "$target" 2>&1; then
        error "  Failed to tag ${local_image} -> ${target}"
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

# Source the shared image catalog (defines push_test_images and arrays).
# shellcheck source=../test-images.sh
source "${MANIFESTS_DIR}/test-images.sh"

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
    info "  JFrog test environment setup"
    info "============================================"
    echo ""

    validate_args
    check_prerequisites
    check_repository
    podman_login
    push_test_images
    print_summary

    if [[ $PUSH_FAIL -gt 0 ]]; then
        exit 1
    fi
}

main
