# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

Python 3.12 is required. A pre-provisioned virtualenv lives at `venv/` (gitignored) — use it instead of system `python`/`pip`:

```bash
source venv/bin/activate                    # then plain `pytest`, `ruff`, `pip` work
# or invoke directly without activating:
./venv/bin/pytest tests/ -v
./venv/bin/ruff check .
./venv/bin/python ./image-cgroupsv2-inspector --help
```

If `venv/` is missing, create it with `python3.12` (not `python3`/`python`, which may resolve to a different version) and install from `requirements.txt`:

```bash
python3.12 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/pip install ruff pytest pytest-cov     # dev tools, not in requirements.txt
```

## Common commands

```bash
# Lint / format (matches CI)
ruff check .
ruff format --check .

# Tests (pytest, with src on the path via pyproject.toml)
pytest tests/ -v
pytest tests/test_image_analyzer.py -v                # one file
pytest tests/test_image_analyzer.py::test_name -v     # one test
pytest tests/ --cov=src --cov-report=term-missing     # with coverage

# Run the tool (the CLI is the executable file at the repo root, not a module)
./image-cgroupsv2-inspector --help

# Container build (UBI 9 + Python 3.12 + podman + acl + golang)
podman build -t image-cgroupsv2-inspector -f Containerfile .
```

CI (`.github/workflows/ci.yml`) runs lint → test → container-build sequentially; `ruff format --check` must pass — run `ruff format .` before pushing.

## Architecture

The tool inspects container images for cgroups v2 compatibility in two modes that share a single analysis pipeline. Understanding the layering matters because changes in one mode usually need a mirror change in the other.

### Two collectors, one orchestrator, one CSV schema

- `src/openshift_client.py` + `src/image_collector.py` — OpenShift mode. Talks to the cluster API, walks Pods/Deployments/DeploymentConfigs/StatefulSets/DaemonSets/Jobs/CronJobs/ReplicaSets, and resolves short-name images to FQDN by reading `status.containerStatuses[*].image` from running pods.
- `src/quay_client.py` + `src/registry_collector.py` — Registry mode. Talks to the Quay REST API, enumerates repos/tags in an organization, applies include/exclude/latest-only tag filters.
- Both collectors emit **plain dicts** that conform to the unified schema in `registry_collector.CSV_COLUMNS`. `source` is `"openshift"` or `"registry"`. Adding a column means updating `CSV_COLUMNS`, the `ANALYSIS_KEYS` tuple in `scan_state.py` (if it's an analysis result), and the `_apply_results` mapping in `analysis_orchestrator.py`.
- `src/analysis_orchestrator.py` is **source-agnostic**: it consumes the dicts, calls `ImageAnalyzer.analyze_image()` per unique `image_name`, applies the result back to every record sharing that name, and saves the CSV after each image (crash resilience).

The CLI entrypoint `image-cgroupsv2-inspector` (no `.py` extension; `argparse`-driven, ~1080 lines) wires up which collector to use based on `--registry-url` vs `--api-url` (mutually exclusive). It is the **only** caller of the orchestrator and is where mode-specific output paths and pull-secret handling live.

### Image analysis pipeline (`src/image_analyzer.py`)

For each unique image name, `ImageAnalyzer.analyze_image()`:
1. `podman pull` (rewriting `image-registry.openshift-image-registry.svc:5000/...` URLs to the external route in OpenShift mode, using `--tls-verify=false` since the route is typically self-signed).
2. Exports the container filesystem to `<rootfs_base>/rootfs/`.
3. Walks the rootfs for Java/Node/.NET binaries (regex patterns + exclusion prefixes for `/etc/alternatives/`, `node_modules/`, etc.), runs `-version`/`--list-runtimes`, and applies the version-matrix in the module docstring.
4. **Go scan** (when `go` is on `PATH` and `--disable-go` not set): resolves ENTRYPOINT/CMD via `podman inspect`, runs `go version` and `go version -m` against candidate binaries, applies the matrix in `src/go_scan.py` (Go ≥1.19 = compatible; older Go needs a v2-aware module at minimum version).
5. **Deep scan** (`src/deep_scan.py`, opt-in via `--deep-scan`): scans entrypoint scripts (high confidence), source/`.`/`exec` chains up to depth 5 (medium), and `strings` output of binaries (low) for cgroup v1 paths. Flags `v2_aware=true` when v1 patterns coexist with v2 patterns in the same file.
6. Cleans up the image and exported rootfs.

Per-image work is wrapped in a SIGALRM timer (`--image-timeout`, default 600s). The timeout exception inherits from `BaseException` (not `Exception`) so that broad `except Exception` handlers inside `_run_command`/`_extract_tar` don't swallow it. Timed-out images are skipped, and the tool exits with code `2` (vs `0` clean / `1` error).

### Resume / state (`src/scan_state.py`)

Every `--analyze` run writes `.state_<target>.json` (target = cluster name or registry host) atomically after each image. The state file tracks three buckets: `completed_images` (skipped on resume), `error_images` and `timeout_images` (retried on resume). Cached analysis results in `image_results` are restored into the CSV on resume so prior successful work is never lost. Bumping `STATE_VERSION` requires backward compatibility consideration — the resume path warns on mismatch but still proceeds.

### HTML report (`src/html_reporter.py`, `src/templates/`)

Aggregates the CSV by `image_name`, renders `report.html.j2` with all DataTables JS/CSS inlined from `src/templates/assets/` so the report works air-gapped. Triggered by `--html-report` during a scan, or by `--report-only <csv>` to regenerate offline.

## Project-specific invariants

- **CHANGELOG must be updated for every user-visible change.** Add a concise entry under `## [Unreleased]` (Added / Changed / Fixed) in the same change that introduces the feature or fix — not in a follow-up. `[Unreleased]` accumulates until the next release tag, when it's renamed to the version. Keep entries terse — one or two short bullets, not paragraphs; the verbose explanation belongs in the PR/commit body.
- **Version is single-sourced.** `src/__init__.py:__version__` and `pyproject.toml:version` must match. Convention: git tag `vX.Y` ↔ `"X.Y.0"`, hotfixes `vX.Y.Z` ↔ `"X.Y.Z"`. Bumping requires editing both files.
- **Filesystem extraction is the source of truth.** OCI manifests, image labels, and `podman inspect` config are intentionally **not** used to gate or replace the rootfs scan — they're a known blind spot of this scanner (an image can claim to be Java 21 in metadata while shipping Java 8). When tempted to add a metadata-based shortcut, don't; extend the filesystem scan instead.
- **`prompts/` is a gitignored maintainer workspace** (`prompts/ROADMAP.md` and siblings are local-only). Edits there should leave `git status` clean.
- **Don't make git writes without explicit instruction.** Read-only git is fine; `add`/`commit`/`push`/`tag`/`reset` need an in-turn ask. The maintainer commits by hand.
- **`registries.conf`-style short names are resolved at collection time, not pull time.** The OpenShift collector reads the resolved FQDN from pod status because the host running the tool generally doesn't share the cluster's `unqualified-search-registries`.
