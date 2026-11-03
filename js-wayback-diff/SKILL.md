---
name: js-wayback-diff
description: >
  Mine historical JavaScript from the Wayback Machine: build a timeline per bundle, download sampled
  snapshots, and diff them against the current corpus to recover API paths, hosts and parameters that no
  longer appear in production JS. Use when the user wants historical JS analysis, wayback diffing, old
  endpoints, or removed features before testing.
---

# Historical JavaScript diffing

Current JS is only the surface that survived. Archived bundles keep endpoints,
staging hosts, feature flags and parameters that were removed from the UI but
may still be routed server-side. This skill recovers them from the Wayback
Machine and turns them into leads.

It never sends traffic to the target. Only `web.archive.org` is contacted.

## Why the timeline

A single "old vs new" comparison is noisy and misses evolution. Sample one
snapshot per window (default every 90 days), then compare each sampled version
against the current bundle. That keeps the run bounded while still covering
years of change.

Timeline policy:

- Default window: 24 months, 90-day step, 6 snapshots per URL, 40 URLs.
- Old programs: start at 24 months. Expand with `--months 120 --step-days 180`
  only where the diff produced leads; a 4-decade sweep of every bundle is not a
  useful first pass.
- `--host-scan` finds `.js` URLs in the CDX index that the current corpus never
  referenced (old bundle names). Enable it for thin current corpora.
- Rate limit is 1 request/second by default. Do not lower it; archive.org
  throttles aggressively and a 429 storm wastes the run.

## Run

```bash
# once js-acquire has produced raw/manifest.json
python3 .opencode/skills/js-wayback-diff/scripts/wayback_timeline.py \
  --root targets/<target>/artifacts/recon/js \
  --domain example.com --months 24 --step-days 90 --host-scan

python3 .opencode/skills/js-wayback-diff/scripts/jsdiff.py \
  --root targets/<target>/artifacts/recon/js --domain example.com
```

Useful flags:

- `--dry-run` — query CDX and build `raw/timeline.jsonl` without downloading
- `--max-urls 40`, `--max-snapshots 6` — bound the run
- `--months`, `--step-days` — timeline density
- `--rate 1.0` — seconds between archive requests

## Checklist and gates

Long historical runs are exactly where an agent stops early. Before starting,
load `unlazy` and write `GATES.md` with one gate per URL group and one for the
diff. Create or extend `checklist.md`:

```markdown
- [ ] CDX inventory | artifact: raw/timeline.jsonl | log: logs/wayback.log
- [ ] Snapshot download | artifact: raw/historical/ | log: logs/wayback.log
- [ ] Diff current vs historical | artifact: findings/historical.jsonl | log: logs/jsdiff.log
- [ ] Historical summary | artifact: findings/historical-summary.md | log: logs/jsdiff.log
```

Verify before reporting:

```bash
python3 .opencode/skills/js-wayback-diff/scripts/verify_checklist.py \
  targets/<target>/artifacts/recon/js --checklist targets/<target>/artifacts/recon/js/checklist.md
```

## Output

- `raw/timeline.jsonl` — URL, timestamp, archive URL, local file, hash, size
- `raw/historical/<host>/<timestamp>__<name>.js` — original archived bytes
- `diffs/<slug>_<timestamp>.diff` — historical-only and current-only symbols
- `findings/historical.jsonl` — per pair: old-only paths, hosts, parameters
- `findings/historical-summary.md` — ranked readable summary
- `findings/endpoints.jsonl` — historical-only leads appended, so
  `make_requests.py` turns them into ready-to-fire requests

## How to read the diff

- `- /path` lines exist in the archived bundle and not in current production.
  Those are the leads; rank them by `admin`, `internal`, `api`, version
  segments, `graphql`, `upload`, `payment`, `invite`, `export`.
- Old hosts (staging, internal APIs) are leads for scope questions, not for
  scanning. If a host is outside the recorded scope, report it, do not touch it.
- Old parameter names are useful even when the endpoint survived: they hint at
  mass assignment, hidden filters, and debug switches.
- A path that 404s today can still be alive behind a different base path.
  Confirm with low-rate requests only after authorization.

## Limits

- Wayback coverage is incomplete; a missing snapshot is not proof a file never
  existed.
- Hashed bundle names change on every build, so per-URL timelines are sparse.
  `--host-scan` compensates by discovering old names.
- Minified line diffs are unreadable. This skill diffs extracted symbol sets
  (paths, hosts, params), not raw lines. That is deliberate.
- Archived JS may include third-party vendor code. Do not treat a vendor path as
  a target endpoint.
- Do not fetch the same snapshot twice; the timeline script reuses local files
  by path.

## Handoff

`js-security-analysis` consumes `findings/historical.jsonl` and folds old-only
leads into the feature map. `make_requests.py` turns appended endpoint leads
into `findings/requests/` with placeholders for your own session.
