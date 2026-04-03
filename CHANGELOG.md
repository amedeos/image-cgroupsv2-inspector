# Changelog

All notable changes to this project will be documented in this file.

## [2.0.0] — Unreleased

### Added
- **Quay registry scan mode**: scan container images directly from a
  Quay registry for cgroups v2 compatibility without requiring an
  OpenShift cluster connection
- New CLI options: `--registry-url`, `--registry-token`, `--registry-org`,
  `--registry-repo`, `--include-tags`, `--exclude-tags`, `--latest-only`
- Environment variable support for registry mode:
  `QUAY_REGISTRY_URL`, `QUAY_REGISTRY_TOKEN`, `QUAY_REGISTRY_ORG`
- Unified CSV schema with `source`, `registry_org`, `registry_repo` columns
- `AnalysisOrchestrator` for source-agnostic image analysis with
  incremental CSV saving
- Automatic `auth.json` generation from Quay token for podman pulls
- Tag filtering with glob patterns (include/exclude) and latest-only
- Quay test environment setup/teardown scripts
  (`manifests/quay/quay-setup.sh`, `manifests/quay/quay-teardown.sh`)
- Comprehensive unit tests for all new modules
- CLI integration tests for registry mode

### Changed
- Main script now supports dual-mode operation
  (OpenShift and registry are mutually exclusive)
- Image analysis extracted from `ImageCollector` into
  `AnalysisOrchestrator` (shared by both modes)
- CSV output now includes 3 additional columns (`source`,
  `registry_org`, `registry_repo`) — backward compatible
- Version bumped to 2.0.0
- GitHub Actions CI updated to run on feature branches
- OpenShift test manifests moved from `test/` to `manifests/cluster/`
- Docker/container support added (Containerfile by @beelzetron)

### Fixed
- Registry mode no longer uses stale `.pull-secret` from previous
  OpenShift scans (#34)

## [1.6] — 2026-03-29

### Added
- Docker support with Containerfile (@beelzetron)
- GitHub CI and pytest
- Moved cluster sample manifests to `manifests/cluster/`

## [1.5] — 2026-03-09

### Added
- `--skip-disk-check` option
- Fix podman info check on some podman versions

## [1.4] — 2026-02-24

### Fixed
- Error reporting for podman operations
- Pull-secret handling improvements

## [1.3] — 2026-02-24

### Added
- Internal registry support (auto-detect and custom route)
- Fix _find_binaries hang on absolute symlinks

## [1.2] — 2026-02-09

### Added
- DeploymentConfig support

## [1.1] — 2026-02-09

### Added
- Short-name image resolution

## [1.0] — 2026-02-05

### Added
- Initial release
- OpenShift cluster scanning for cgroups v2 compatibility
- Java, Node.js, .NET runtime detection
- CSV output with analysis results
