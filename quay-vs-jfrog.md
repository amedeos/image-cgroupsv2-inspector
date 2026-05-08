# Quay vs JFrog Container Registry — API Comparison

This document captures the differences between the Quay REST API and the JFrog
Artifactory + Docker Registry v2 API set, as they show up in this project's
client modules:

- `src/quay_client.py` — Quay client used by `src/registry_collector.py`
- `src/jfrog_client.py` — JFrog client used by `src/jfrog_collector.py`

The unified CSV schema (see `src/registry_collector.CSV_COLUMNS`) lets the
analysis pipeline stay source-agnostic, but the collection layer has to deal
with two registries that behave very differently. Read this when porting
behaviour between the two clients or extending either to a new endpoint.

---

## Fundamental model differences

| Aspect | Quay | JFrog |
|--------|------|-------|
| **Hierarchy** | `organization → repository → tag` (3 levels) | `repository (key) → image → tag` (3 levels, but "repository" is the *container* like `docker-local`, not a single image) |
| **CSV schema mapping** | `registry_org=org`, `registry_repo=repo` | `registry_org=repo-key`, `registry_repo=image` |
| **API tier** | Single tier, every endpoint available everywhere | Pro vs CE split: e.g. `/api/repositories/{key}` returns HTTP 400 with `"This REST API is available only in Artifactory Pro"` on Community Edition |
| **Content negotiation** | Everything is `application/json` | Mixed: `/api/system/ping` returns `text/plain` and refuses `Accept: application/json` with HTTP 406 — the client must override `Accept` for that endpoint |

---

## Endpoint-by-endpoint comparison

| Capability | Quay endpoint | JFrog endpoint | Notes |
|------------|---------------|----------------|-------|
| **Base path** | `/api/v1` | `/artifactory/api` | |
| **Auth header** | `Authorization: Bearer <oauth-token>` | `Authorization: Bearer <access-token>` | Same wire format, different token sources (Quay Application Token vs JFrog Identity / Access Token) |
| **Connectivity check** | `GET /user/` (requires the *Read User Information* permission) | `GET /api/system/ping` (returns `OK` as `text/plain`) | JFrog ping has no permission requirement; Quay's user endpoint requires the token to actually carry the user-info scope |
| **Verify org/repo exists** | `GET /organization/{org}` | **CE-friendly:** `GET /api/repositories?type=local` + client-side grep for the desired key. The Pro endpoint `GET /api/repositories/{key}` is intentionally avoided. | |
| **List repositories** | `GET /repository?namespace={org}` with `next_page` cursor | `GET /api/repositories?type={type}` (no pagination) | Quay paginates; JFrog returns the full list in one call |
| **List images inside a repo** | n/a — Quay has no equivalent layer | `GET /api/docker/{repo}/v2/_catalog` (Docker Registry v2) with cursor `last=<last-image>` and `n=<page-size>` | JFrog leans on the standard Docker Registry v2 API for image enumeration |
| **List tags** | `GET /repository/{org}/{repo}/tag/?onlyActiveTags=true&limit=100&page=N` | `GET /api/docker/{repo}/v2/{image}/tags/list` | |
| **Tag metadata** | Tag response already includes `manifest_digest`, `size`, `last_modified`, `start_ts` (epoch) | `tags/list` returns **only the array of names** — to get `lastModified` (ISO 8601) you need a follow-up `GET /api/storage/{repo}/{image}/{tag}` per tag | This is the single biggest cost difference, see *Cost / latency* below |

---

## Pagination

| | Quay | JFrog |
|--|------|-------|
| **Repos** | Cursor `next_page` (string) | None — single response |
| **Tags** | Page-based: `page=N` + `has_additional` boolean | None on `tags/list` |
| **Docker catalog** | n/a | Cursor `last=<image>` + `n=<page-size>` |

---

## Server-side filtering

| Filter | Quay | JFrog |
|--------|------|-------|
| Skip non-`NORMAL` repository state (mirror, marked-for-delete, …) | Yes, server filters via the `state` field on the repository object | No equivalent concept on the wire |
| Active tags only | `onlyActiveTags=true` query parameter | n/a — `tags/list` always returns everything; filter client-side |

**Consequence:** in JFrog all the include/exclude/latest-only logic is
client-side. The shared helper `src/_registry_filters.filter_tags()` works
because both collectors emit dicts with `name` and `start_ts` (epoch) keys —
`RegistryCollector` reads `start_ts` straight from Quay's JSON, while
`JfrogCollector` derives it via `JfrogClient._iso8601_to_epoch()` from the
`lastModified` field returned by `/api/storage`.

---

## Cost / latency

For 21 images × N tags each:

**Quay** — roughly 23 round trips (cursor-paginated tag list, but each tag
arrives with full metadata):
- 1 × org check
- 1 × repo list (potentially paginated)
- 21 × tag list (each potentially paginated, each tag entry already
  carries `start_ts`, `last_modified`, `manifest_digest`, `size`)

**JFrog** — at least `1 + 21 + ΣN` round trips:
- 1 × `/v2/_catalog` (paginated if >100 images)
- 21 × `/v2/{image}/tags/list` (one per image)
- **ΣN × `/api/storage/{repo}/{image}/{tag}`** (one per tag, the expensive
  part) for `lastModified`

In practice JFrog needs **roughly N times more network round trips** than
Quay to populate the same metadata. There is no public bulk-metadata
endpoint that bypasses this on CE; only AQL (Artifactory Query Language,
Pro-only) can collapse it into a single call.

---

## Delete (used by the teardown scripts)

| Operation | Quay | JFrog |
|-----------|------|-------|
| Delete a "repository" wholesale | `DELETE /api/v1/repository/{org}/{repo}` (removes every tag) | `DELETE /artifactory/{repo}/{image}` (removes the Docker folder for that image, all tags included) |
| Delete a single tag | `DELETE /api/v1/repository/{org}/{repo}/tag/{tag}` | Docker Registry v2 standard `DELETE /v2/{repo}/{image}/manifests/{digest}` |

**Asymmetry to remember:** in Quay a "repository" *is* a single image, so
deleting it cleans up that image entirely. In JFrog the "repository" is
the Docker root (e.g. `docker-local`); deletion typically targets the
Docker *image folder* one level below, never the repository key itself
(which would require admin permissions and a much heavier REST call).
The teardown scripts in `manifests/quay/` and `manifests/jfrog/` reflect
this difference: same observable behaviour ("clean up every test image"),
different endpoints under the hood.

---

## Response shape examples

### Quay — `GET /api/v1/repository/{org}/{repo}/tag/`

```json
{
  "tags": [
    {
      "name": "17",
      "manifest_digest": "sha256:…",
      "size": 12345678,
      "last_modified": "Wed, 07 May 2026 19:29:19 -0000",
      "start_ts": 1778174959
    }
  ],
  "page": 1,
  "has_additional": false
}
```

Everything the collector needs is already in this payload.

### JFrog — `GET /artifactory/api/docker/{repo}/v2/{image}/tags/list`

```json
{
  "name": "docker-local/java-compatible",
  "tags": ["17", "17-20260507", "latest", "dev"]
}
```

Notice: just names, no timestamps, no digests. To match Quay's shape the
client then issues, per tag:

### JFrog — `GET /artifactory/api/storage/{repo}/{image}/{tag}`

```json
{
  "repo": "docker-local",
  "path": "/java-compatible/17",
  "created": "2026-05-07T19:29:19.323+02:00",
  "createdBy": "admin",
  "lastModified": "2026-05-07T19:29:19.323+02:00",
  "modifiedBy": "admin",
  "lastUpdated": "2026-05-07T19:29:19.323+02:00",
  "children": [{"uri": "/manifest.json", "folder": false}]
}
```

`JfrogClient._iso8601_to_epoch("2026-05-07T19:29:19.323+02:00")` →
`1778174959`, mapped to `start_ts` so the shared `filter_tags()` helper can
sort tags by recency uniformly.

---

## Practical takeaways (when porting Quay logic to JFrog)

1. **No tag metadata in `tags/list`.** If Quay code uses `start_ts`,
   `last_modified` or `manifest_digest`, the JFrog port needs an extra
   round trip per tag. Wrap it behind a `fetch_timestamps=True` flag so
   callers that don't need the data can skip the extra hits (see
   `JfrogClient.list_tags`).
2. **Pro-only endpoints exist.** Anything under `/api/repositories/{key}`
   is gated to Pro / Enterprise. CE deployments answer with HTTP 400 and
   a literal `"This REST API is available only in Artifactory Pro"` body.
   List + filter client-side instead.
3. **Mixed content types.** `/api/system/ping` is `text/plain`. Either
   override `Accept` per-call or build the client with `Accept: */*` and
   pay slightly less explicit content-type validation. We chose the
   per-call override.
4. **Filter logic must move client-side.** Don't assume server-side
   `onlyActiveTags`-style filtering — replicate it in Python with the
   shared `_registry_filters.filter_tags()` helper.
5. **Deletion semantics differ.** Don't translate
   `DELETE /api/v1/repository/{org}/{repo}` to
   `DELETE /api/repositories/{key}` — the former wipes one image, the
   latter would wipe the entire JFrog repository (and on CE returns
   HTTP 400 anyway). The right port is
   `DELETE /artifactory/{repo}/{image}`.

All five caveats are encoded in the current `JfrogClient` implementation;
this file is the human-readable explanation of *why* the code looks the
way it does.
