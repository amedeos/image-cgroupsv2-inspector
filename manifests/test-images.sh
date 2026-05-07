#!/bin/bash
###############################################################################
# test-images.sh — Shared test-image catalog for setup/teardown scripts.
#
# Sourced by manifests/quay/quay-setup.sh, quay-teardown.sh and
# manifests/jfrog/jfrog-setup.sh, jfrog-teardown.sh. Defines the canonical
# list of test images and a push_test_images() driver. The destination
# registry, organization and authentication are entirely the caller's
# responsibility — this file only knows what to push, not where.
#
# Caller contract (must be defined BEFORE sourcing this file):
#   - DATE_TAG               date string, e.g. $(date +%Y%m%d)
#   - CONTAINERFILES_DIR     directory holding the deep-scan-images/* contexts
#                            (typically manifests/quay/deep-scan-images)
#
# Caller contract (must be defined or sourced BEFORE calling
# push_test_images, but may be defined after sourcing this file since
# bash resolves function names at call time):
#   - pull_tag_push UPSTREAM REPO TAG
#   - add_tag REPO SOURCE_TAG NEW_TAG
#   - build_and_push CONTEXT_DIR CONTAINERFILE_NAME REPO TAG
#   - info / success / warn / error log helpers
###############################################################################

# Destination repository names (used by teardown scripts).
TEST_REPOS=(
    java-compatible
    java-incompatible
    node-compatible
    node-incompatible
    dotnet-compatible
    dotnet-incompatible
    no-runtime
    deep-scan-entrypoint-cgv1
    deep-scan-source-cgv1
    deep-scan-binary-cgv1
    deep-scan-exec-cgv1
    deep-scan-cadvisor
    deep-scan-node-exporter
    deep-scan-nginx-negative
    deep-scan-redis-negative
    deep-scan-go-v2-compliant-runtime
    deep-scan-go-v2-compliant-automaxprocs
    deep-scan-go-v2-compliant-lib-only
    deep-scan-go-v2-needs-review
    deep-scan-go-v2-unaware
    deep-scan-c-binary-no-go
    deep-scan-go-v2-compliant-combo
)

# Upstream images pulled by setup (used by teardown to remove local copies).
UPSTREAM_TEST_IMAGES=(
    "registry.access.redhat.com/ubi8/openjdk-17:latest"
    "registry.access.redhat.com/ubi8/openjdk-8:1.14"
    "docker.io/library/node:20-slim"
    "docker.io/library/node:18-slim"
    "mcr.microsoft.com/dotnet/runtime:8.0"
    "mcr.microsoft.com/dotnet/core/runtime:3.0"
    "registry.access.redhat.com/ubi9-minimal:latest"
    "gcr.io/cadvisor/cadvisor:v0.44.0"
    "docker.io/prom/node-exporter:v1.3.1"
    "docker.io/library/nginx:1.25-alpine"
    "docker.io/library/redis:7-alpine"
)

# ---------------------------------------------------------------------------
# Push driver: pulls/builds every test image and pushes it to the destination
# registry. Relies on pull_tag_push / add_tag / build_and_push from the caller.
# ---------------------------------------------------------------------------
push_test_images() {
    if [[ -z "${CONTAINERFILES_DIR:-}" ]]; then
        error "CONTAINERFILES_DIR must be set before calling push_test_images"
        exit 1
    fi
    if [[ -z "${DATE_TAG:-}" ]]; then
        error "DATE_TAG must be set before calling push_test_images"
        exit 1
    fi

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

    # ================================================================
    # Deep-scan test images (--deep-scan heuristic analysis)
    # ================================================================
    echo ""
    info "================================================================"
    info "  Deep-scan test images (--deep-scan heuristic analysis)"
    info "================================================================"
    echo ""

    info "=== deep-scan-entrypoint-cgv1 (entrypoint with cgroup v1 paths) ==="
    build_and_push "${CONTAINERFILES_DIR}/entrypoint-cgv1" \
        "Containerfile" "deep-scan-entrypoint-cgv1" "latest" || true
    add_tag "deep-scan-entrypoint-cgv1" "latest" "v1.0-${DATE_TAG}" || true
    podman rmi "deep-scan-entrypoint-cgv1:latest" 2>/dev/null || true
    echo ""

    info "=== deep-scan-source-cgv1 (sourced scripts with cgroup v1 paths) ==="
    build_and_push "${CONTAINERFILES_DIR}/source-cgv1" \
        "Containerfile" "deep-scan-source-cgv1" "latest" || true
    add_tag "deep-scan-source-cgv1" "latest" "v1.0-${DATE_TAG}" || true
    podman rmi "deep-scan-source-cgv1:latest" 2>/dev/null || true
    echo ""

    info "=== deep-scan-binary-cgv1 (Go binary with cgroup v1 strings) ==="
    build_and_push "${CONTAINERFILES_DIR}/binary-cgv1" \
        "Containerfile" "deep-scan-binary-cgv1" "latest" || true
    add_tag "deep-scan-binary-cgv1" "latest" "v1.0-${DATE_TAG}" || true
    podman rmi "deep-scan-binary-cgv1:latest" 2>/dev/null || true
    echo ""

    info "=== deep-scan-exec-cgv1 (shell entrypoint exec's Go binary with cgroup v1 strings) ==="
    build_and_push "${CONTAINERFILES_DIR}/exec-cgv1" \
        "Containerfile" "deep-scan-exec-cgv1" "latest" || true
    add_tag "deep-scan-exec-cgv1" "latest" "v1.0-${DATE_TAG}" || true
    podman rmi "deep-scan-exec-cgv1:latest" 2>/dev/null || true
    echo ""

    # ================================================================
    # Go cgroups v2 compliance test images
    # ================================================================
    echo ""
    info "================================================================"
    info "  Go cgroups v2 compliance test images"
    info "================================================================"
    echo ""

    info "=== deep-scan-go-v2-compliant-runtime (Go 1.22, no cgroup libs) ==="
    build_and_push "${CONTAINERFILES_DIR}/go-v2-compliant-runtime" \
        "Containerfile" "deep-scan-go-v2-compliant-runtime" "latest" || true
    add_tag "deep-scan-go-v2-compliant-runtime" "latest" "v1.0-${DATE_TAG}" || true
    podman rmi "deep-scan-go-v2-compliant-runtime:latest" 2>/dev/null || true
    echo ""

    info "=== deep-scan-go-v2-compliant-automaxprocs (Go 1.22 + automaxprocs v1.6.0) ==="
    build_and_push "${CONTAINERFILES_DIR}/go-v2-compliant-automaxprocs" \
        "Containerfile" "deep-scan-go-v2-compliant-automaxprocs" "latest" || true
    add_tag "deep-scan-go-v2-compliant-automaxprocs" "latest" "v1.0-${DATE_TAG}" || true
    podman rmi "deep-scan-go-v2-compliant-automaxprocs:latest" 2>/dev/null || true
    echo ""

    info "=== deep-scan-go-v2-compliant-lib-only (Go 1.18 + automaxprocs v1.5.1) ==="
    build_and_push "${CONTAINERFILES_DIR}/go-v2-compliant-lib-only" \
        "Containerfile" "deep-scan-go-v2-compliant-lib-only" "latest" || true
    add_tag "deep-scan-go-v2-compliant-lib-only" "latest" "v1.0-${DATE_TAG}" || true
    podman rmi "deep-scan-go-v2-compliant-lib-only:latest" 2>/dev/null || true
    echo ""

    info "=== deep-scan-go-v2-needs-review (Go 1.18 + automaxprocs v1.4.0) ==="
    build_and_push "${CONTAINERFILES_DIR}/go-v2-needs-review" \
        "Containerfile" "deep-scan-go-v2-needs-review" "latest" || true
    add_tag "deep-scan-go-v2-needs-review" "latest" "v1.0-${DATE_TAG}" || true
    podman rmi "deep-scan-go-v2-needs-review:latest" 2>/dev/null || true
    echo ""

    info "=== deep-scan-go-v2-unaware (Go 1.18, no cgroup libs) ==="
    build_and_push "${CONTAINERFILES_DIR}/go-v2-unaware" \
        "Containerfile" "deep-scan-go-v2-unaware" "latest" || true
    add_tag "deep-scan-go-v2-unaware" "latest" "v1.0-${DATE_TAG}" || true
    podman rmi "deep-scan-go-v2-unaware:latest" 2>/dev/null || true
    echo ""

    info "=== deep-scan-c-binary-no-go (C binary, negative control for Go detection) ==="
    build_and_push "${CONTAINERFILES_DIR}/c-binary-no-go" \
        "Containerfile" "deep-scan-c-binary-no-go" "latest" || true
    add_tag "deep-scan-c-binary-no-go" "latest" "v1.0-${DATE_TAG}" || true
    podman rmi "deep-scan-c-binary-no-go:latest" 2>/dev/null || true
    echo ""

    info "=== deep-scan-go-v2-compliant-combo (Go 1.22 + automaxprocs v1.6.0 + automemlimit v0.7.0) ==="
    build_and_push "${CONTAINERFILES_DIR}/go-v2-compliant-combo" \
        "Containerfile" "deep-scan-go-v2-compliant-combo" "latest" || true
    add_tag "deep-scan-go-v2-compliant-combo" "latest" "v1.0-${DATE_TAG}" || true
    podman rmi "deep-scan-go-v2-compliant-combo:latest" 2>/dev/null || true
    echo ""

    # --- deep-scan-cadvisor (upstream, cgroup v1 positive) ---
    info "=== deep-scan-cadvisor (cAdvisor v0.44.0, cgroup v1 positive) ==="
    pull_tag_push "gcr.io/cadvisor/cadvisor:v0.44.0" \
        "deep-scan-cadvisor" "v0.44.0" || true
    add_tag "deep-scan-cadvisor" "v0.44.0" "v0.44.0-${DATE_TAG}" || true
    add_tag "deep-scan-cadvisor" "v0.44.0" "latest" || true
    echo ""

    # --- deep-scan-node-exporter (upstream, cgroup v1 positive) ---
    info "=== deep-scan-node-exporter (Prometheus node-exporter v1.3.1, cgroup v1 positive) ==="
    pull_tag_push "docker.io/prom/node-exporter:v1.3.1" \
        "deep-scan-node-exporter" "v1.3.1" || true
    add_tag "deep-scan-node-exporter" "v1.3.1" "v1.3.1-${DATE_TAG}" || true
    add_tag "deep-scan-node-exporter" "v1.3.1" "latest" || true
    echo ""

    # --- deep-scan-nginx-negative (upstream, negative control) ---
    info "=== deep-scan-nginx-negative (nginx 1.25-alpine, negative control) ==="
    pull_tag_push "docker.io/library/nginx:1.25-alpine" \
        "deep-scan-nginx-negative" "1.25" || true
    add_tag "deep-scan-nginx-negative" "1.25" "1.25-${DATE_TAG}" || true
    add_tag "deep-scan-nginx-negative" "1.25" "latest" || true
    echo ""

    # --- deep-scan-redis-negative (upstream, negative control) ---
    info "=== deep-scan-redis-negative (redis 7-alpine, negative control) ==="
    pull_tag_push "docker.io/library/redis:7-alpine" \
        "deep-scan-redis-negative" "7" || true
    add_tag "deep-scan-redis-negative" "7" "7-${DATE_TAG}" || true
    add_tag "deep-scan-redis-negative" "7" "latest" || true
    echo ""
}
