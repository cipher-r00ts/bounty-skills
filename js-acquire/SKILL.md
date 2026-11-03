---
name: js-acquire
description: >
  Collect JavaScript for an authorized target before security analysis: browser-captured external and
  inline scripts, lazy-loaded bundles, sourcemaps, and historical URLs. Use when asked to gather JS,
  download bundles, capture scripts from a site, or feed js-security-analysis. Browser-first through
  agent-browser and Caido.
---

# JavaScript acquisition

Acquire the broadest defensible set of JavaScript for an authorized target, with
provenance. This skill is about collection only: `js-security-analysis` consumes
its output, and `js-wayback-diff` handles deep historical diffing.

## Run root

Keep one root per target. In this workspace the convention is:

```text
targets/<target>/artifacts/recon/js/
├── checklist.md
├── raw/
│   ├── external/        downloaded .js, original bytes
│   ├── inline/          one file per inline <script> block
│   ├── historical/      archived copies (js-wayback-diff)
│   ├── sourcemaps/      .map files and restored sources
│   ├── pages/           captured HTML for provenance
│   └── manifest.json
├── logs/                one stable log per technique, timestamped entries
└── verification_report.md
```

Use another root with `--root` when working outside a hackbot target. Never mix
targets in one run.

## Step 0 — set up and write the checklist first

```bash
.opencode/skills/js-acquire/scripts/init-run.sh \
  --root targets/<target>/artifacts/recon/js
```

This creates the tree and `checklist.md`. A row is complete only when it is
checked, the artifact is non-empty, and the log exists with a UTC timestamp.
A technique that legitimately found nothing still needs a non-empty log saying
so. Do not tick a row because a command was typed.

For long or multi-part runs, load the `unlazy` skill and write its `GATES.md`
first. That is the countermeasure against an agent declaring collection done
after two tools.

## Step 1 — browser capture (primary)

Browsers are the only reliable way to get the JS a modern app actually loads:
bundles are injected at runtime, routes are lazy, and the HTML shell often has
no useful `<script src>`.

```bash
.opencode/skills/js-acquire/scripts/collect-browser.sh \
  --root targets/<target>/artifacts/recon/js \
  --url https://app.example.com/
```

What it does:

- launches `agent-browser` through the Caido proxy (`127.0.0.1:8081` by default)
  with `--ignore-https-errors`, so every captured page lands in HTTP history
- waits for the app to boot, optionally scrolls to trigger lazy imports
- collects `document.scripts` sources, `performance` script resources, and every
  inline block
- saves the rendered HTML under `raw/pages/`
- downloads each external script byte-for-byte through the same proxy
- hashes, deduplicates and merges into `raw/manifest.json`
- writes `logs/browser-collect.log`

Options:

- `--auth-config /tmp/caido/<host>/auth.cfg` — reuse a Caido `export-curl
  --config` snapshot for authenticated downloads
- `--scroll 5` / `--wait 6` — more lazy bundles on heavy SPAs
- `--max 300` — cap external files
- `--no-proxy` — only when Caido is unavailable
- `--session name` — separate browser session

Limitation: browser-side authentication needs a logged-in profile or an
existing browser session. Passing `--auth-config` authenticates the downloads,
not the browser page. If the page requires a login, say so and capture it
manually through Caido instead of pretending the acquisition is complete.

## Step 2 — secondary sources

Run what is installed; log the rest as unavailable with a reason.

**Live crawl (katana).** Same scope, bounded depth, JS in scope:

```bash
katana -u https://app.example.com/ -d 2 -jc -silent -rl 30 \
  -o /tmp/katana_urls.txt
```

Fetch in-scope `.js` URLs from that list into `raw/external/` with the same
provenance fields.

**Historical URL discovery (waymore / gau / waybackurls).** These find old JS
URLs; fetching them is `js-wayback-diff`'s job. Record the URL lists here:

```bash
waymore -i app.example.com -mode U -o /tmp/waymore_urls.txt
gau app.example.com | grep -Ei '\.js($|\?)' > /tmp/gau_js.txt
waybackurls app.example.com | grep -Ei '\.js($|\?)' > /tmp/wayback_js.txt
```

**Sourcemaps.** For every external file, check its `sourceMappingURL` comment
and the conventional `.map` sibling. Store maps and any `sourcesContent` under
`raw/sourcemaps/`, preserving the parent relation.

**JSLuice (optional).** If `jsluice` is installed, run it over acquired files to
find URLs and dynamic imports, then fetch only in-scope JS-shaped candidates in
a bounded second pass. If it is missing, log that.

**Inline snippets.** The browser capture already writes them to `raw/inline/`.
For pages fetched with curl, extract every `<script>` without `src` and save one
file per block with the source URL and a stable index.

**Mobile (optional).** `apkeep` is not installed here. Only if the authorized
scope includes an app and the tool is available, extract JS/maps from the APK
and record package/version provenance.

## Step 3 — anti-automation ladder

Escalate only when blocked:

1. `curl` — fastest, first to be blocked
2. plain HTTP fetch — same tradeoff
3. `agent-browser` — executes JS, clears basic bot checks (default here)
4. a full browser session through Caido — for heavier anti-bot targets
5. manual browsing with the proxy — say so explicitly when the target needs a
   human, rather than claiming coverage

## Step 4 — dedupe and manifest

Hash every raw file with SHA-256. Deduplicate analysis inputs by hash, but keep
every observed URL, timestamp, source and method in `raw/manifest.json`:

```json
{
  "hash": "sha256:...",
  "sha256": "...",
  "local_path": "raw/external/ab12cd34__main.js",
  "all_urls": ["https://app.example.com/static/main.js"],
  "source_urls": ["https://app.example.com/static/main.js"],
  "method": "browser",
  "category": "external",
  "size_bytes": 48213,
  "captured_at": "2026-11-01T10:00:00+00:00"
}
```

Never discard a distinct byte sequence because the basename matches. Historical
copies of the same URL belong in `raw/historical/` and in the manifest with
`category: historical`.

## Step 5 — verify

```bash
python3 .opencode/skills/js-acquire/scripts/verify_checklist.py \
  targets/<target>/artifacts/recon/js
```

It checks every row, artifact size, log presence and timestamp, then writes
`verification_report.md`. A checked row with an empty artifact or an untimestamped
log fails. Do not report acquisition complete while it exits non-zero.

## Handoff

- `js-security-analysis` — take the run root, not a copy. It expects
  `raw/manifest.json` and the `raw/` tree to be immutable.
- `js-wayback-diff` — when the user wants historical versions diffed, or when
  the current corpus is thin and old bundles may still expose API paths.
- Report unique hashes, counts by category, inline blocks, sourcemaps, and
  limitations (auth-gated pages, missing tools, WAF blocks).
