# Changelog

All notable changes to this project will be documented in this file.

## [2.5.0] — 2026-05-18

### Added
- **HTML report** alongside the CSV output (#62): new `--html-report`
  flag generates a self-contained HTML report (DataTables + Jinja2,
  assets bundled for air-gapped environments) under
  `<output-dir>/html/<basename>.html`. New `--report-only <CSV>` flag
  regenerates the HTML offline from an existing CSV without re-scanning.
  Includes interactive pie chart, clickable status cards, per-runtime
  drill-down filters, and a removable filter banner. Adds
  `not_applicable` overall-status to replace the misleading `unknown`
  fallthrough for images with no detected runtime.
- **Deterministic Go binary cgroups v2 scanning** (#60): replaces the
  heuristic `strings`+`grep` approach with precise `go version` /
  `go version -m` analysis. Go ≥ 1.19 is natively compatible; older
  versions are checked against a v2-aware module matrix
  (`automaxprocs`, `automemlimit`, …). New `--disable-go` CLI flag and
  four new CSV columns (`go_binary`, `go_version`,
  `go_cgroup_v2_compatible`, `go_modules`); the deprecated
  `deep_scan_go_cgroup_libs` column is removed.
- **Node.js sibling-lookup fallback** for musl/Alpine binaries (#61):
  when a `nodeXX_alpine` / `nodeXX_musl` binary fails to execute due to
  a libc / dynamic-linker mismatch (e.g. GitHub Actions Runner images
  shipping both glibc and musl builds side-by-side), the version is now
  inferred from the paired glibc sibling at the same installation path,
  turning previously "Unknown" rows into deterministic Yes/No verdicts.
- Quay infrastructure for Go cgroups v2 compliance test images (#59):
  seven new deep-scan fixture images under
  `manifests/quay/deep-scan-images/go-v2-*/` covering compliant,
  needs-review, and unaware runtime/library combinations.
- `tests/test_version.py` smoke tests guarding against future drift
  between `src/__init__.py:__version__`, `pyproject.toml`, and the main
  script's import.

### Changed
- Align in-repo version to actual release tags and introduce a single
  source of truth (`src/__init__.py:__version__`); `pyproject.toml` and
  the main script now read from it. `--version` and the ASCII banner
  now report the real release version instead of the stale `2.0.0`
  literal that was never released.
- Backfill `CHANGELOG.md` entries for `[2.1.0]` through `[2.4.0]` from
  git history (these releases shipped without changelog updates).

## [2.4.0] — 2026-04-14

### Added
- Detect Go cgroup library imports in binary deep-scan (#56)
- Follow `exec` chains from entrypoint scripts to ELF binaries for deep-scan
- Pre-flight check for `strings` binary when `--deep-scan` is enabled (#54)

### Changed
- Propagate verbose debug logging to log file (#57)

## [2.3.0] — 2026-04-13

### Added
- Deep-scan heuristic mode for cgroup v1 references in entrypoint scripts and binaries (#51)

### Changed
- Move `analysis_error` to last CSV column (#53)

## [2.2.0] — 2026-04-11

### Added
- `--resume` flag to allow restarting interrupted scans (#43, #45)
- `--image-timeout` flag for per-image pull+scan deadline (#42, #44)

## [2.1.0] — 2026-04-10

### Changed
- Handle unknown runtime versions: return "Unknown" compatibility instead of "No" (#40)
- Exclude `node_modules` from binary scan and add "Unknown" count to summary recap (#41)

## [2.0.0] — 2026-04-03

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
- Node.js sibling-lookup fallback: when a `nodeXX_alpine` / `nodeXX_musl`
  binary fails to execute due to a libc / dynamic-linker mismatch (e.g.
  GitHub Actions Runner images shipping both glibc and musl builds
  side-by-side), the version is now inferred from the paired glibc
  sibling binary at the same installation path. This turns previously
  "Unknown" rows into deterministic "Yes" / "No" cgroup v2 compatibility
  verdicts. Cached state files are not invalidated: delete
  `.state_<target>.json` manually to re-scan affected images with the
  new logic.

### Changed
- Main script now supports dual-mode operation
  (OpenShift and registry are mutually exclusive)
- Image analysis extracted from `ImageCollector` into
  `AnalysisOrchestrator` (shared by both modes)
- CSV output now includes 3 additional columns (`source`,
  `registry_org`, `registry_repo`) — backward compatible
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
