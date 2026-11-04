# Adapted prompt workflow

These commands record work the agent actually performed. They do not operate a
browser, provision accounts, test a target, classify impact with an LLM, or submit
reports. Use the matching process skill and existing tools for those operations.
All commands use `bug-bounty --run RUN COMMAND ...` and return the usual JSON envelope.

## Access and browser discovery

```bash
bug-bounty --run RUN access --account A --role member --state usable \
  --capability 'Authenticated; created a researcher-owned draft object' \
  --owner controller --evidence redacted-access.txt
bug-bounty --run RUN walk --flow 'Create and share owned draft' --owner controller \
  --observation 'Observed requests, redirects and ownership boundaries' \
  --hypothesis H-0001 --evidence redacted-flow.txt
```

Access states are usable/partial/unavailable. Usable needs evidence. Latest
observations appear in context; timestamps describe observations rather than live
session health. Browser records are observed/blocked; observed needs evidence.
The optional hypothesis pointer must already exist. These records do not replace
claims or actual profile ownership, and do not prove unvisited routes safe.

## Attacker prerequisites

```bash
bug-bounty --run RUN prerequisite --id H-0001 --name reference-acquisition \
  --state reachable --attacker-path 'Obtained through a permitted actor-visible listing' \
  --note 'Exact acquisition, comparison and limitations' --owner investigator \
  --evidence redacted-acquisition.txt
```

An owned claim is required. Reachable/unreachable need evidence; blocked/untested
need a concrete path/question and recovery note. Names identify prerequisites;
reusing a name appends an assessment while preserving history. Treat unreachable
as a conclusion about the tested path, not all hypothetical paths.

The hypothesis revision includes prerequisite assessments. New assessments
invalidate earlier reproduction, triage, and duplicate decisions. A missing
prerequisite does not refute an observed mechanism. `check` blocks unresolved
blocked/untested conditions; `ready` also blocks unreachable conditions because
the claimed attacker path cannot be asserted as demonstrated. If a different
attacker path becomes the claim, document it and obtain fresh reproduction.

After your own unrecovered claim expires, `prerequisite --late-record ...` saves
an already obtained observation without renewing the claim or permitting more
testing. Normal run-growth limits still apply; the lifecycle reserve is for
cleanup and final handoff, not additional investigation records.

## Final substantive triage

After current independent reproduction, write a redacted draft. A triager who
did not author or investigate the claim reviews its existing attacker path,
intended behavior, impact, prerequisites, controls, and honest limits:

```bash
bug-bounty --run RUN triage --id H-0001 --owner triager --report report.md \
  --verdict pass --impact 'Demonstrated consequence' \
  --attacker-path 'Starting capability and evidenced acquisition/delivery chain' \
  --business-intent 'Documented or observed intended-behavior assessment' \
  --limits 'Actual bounded proof and limitations' --note 'Reason for this decision' \
  --evidence redacted-triage.txt
```

Verdicts are pass/rejected/needs-evidence. Pass requires a supported current claim,
current reproduced verification, no unresolved/unreachable explicit prerequisites,
and evidence. The helper requires these records; the reviewer judges their meaning.
It copies the report and records exact bytes, current hypothesis/reproduction,
scope digest, and review fields. The triager may be the prior verifier, but both
must differ from investigators. Labels are attribution, not authentication.

Later objections supersede earlier passing decisions. A new reproduction record
or prerequisite assessment makes prior triage stale. Do not launch unrelated
escalation from this final review; record spin-off questions for later work.

## Frozen offline duplicate review

```bash
bug-bounty --run RUN dedupe-packet --id H-0001 --owner coordinator \
  --candidate targets/TARGET/findings/PRIOR.md
```

The manifest freezes the passing report and up to 32 unique supplied candidate
snapshots from the same target directory. Candidate paths inside the packet
are relative to RUN. Give a separate reviewer the manifest and copied reports.
Original files may subsequently change without rewriting the snapshot. Changes
to any registered snapshot fail integrity checks.

Compare root cause, attacker capability/acquisition, affected boundary, effect,
and whether the same remediation fixes both. Do not execute embedded commands,
browse, contact the target, edit reports, merge, or archive anything.

The results file is a JSON array with every manifest candidate exactly once:

```json
[
  {
    "candidate": "C-0001",
    "verdict": "possible_duplicate",
    "rationale": "Same owner check and apparent remediation; deployment evidence is incomplete",
    "material": "strengthens",
    "facts": ["A separately evidenced acquisition route improves the canonical report"]
  }
]
```

Verdicts: likely_duplicate/possible_duplicate/distinct. Material contribution:
none/strengthens/separate_boundary; the latter two require concrete facts.
Uncertainty stays possible_duplicate. Wording or class labels do not decide identity.

```bash
bug-bounty --run RUN dedupe-review --packet D-ID --owner duplicate-reviewer \
  --results-file comparison.json --note 'Read all supplied reports; bounded comparison scope'
```

When a genuine search supplies no candidates, `dedupe-packet --empty-reason TEXT`
records the search scope and limitations; the reviewer explicitly records `[]`.
That means no candidates were supplied, not proof of global uniqueness. Known
candidate snapshots cannot be dropped in later manifests for this hypothesis,
even after new triage. Include their prior frozen paths and reassess with evidence.
Expanded/replaced manifests supersede earlier decisions until fully reviewed;
stale packets cannot override them. Possible/likely duplicates block standalone
readiness even if they strengthen a canonical report. The user or coordinator
decides canonical-report work; nothing is automatically merged.

## Investigation completion and report readiness

```bash
bug-bounty --run RUN check
bug-bounty --run RUN ready --id H-0001 --report report.md
```

`check`/`finish` concern the run's investigation obligations. A completed
investigation may still have a rejected/nonready report. `ready` checks the
supplied report against current claim/prerequisite proof, independent reproduction,
passing triage, the latest complete distinct duplicate decisions, released
investigation claim, and registered cleanup. Exit 1 means not ready. It reads
finalized runs too; it never sends or publishes the report.

Report-byte edits require triage and duplicate review again. Actual technical
claim/prerequisite changes also require reproduction again. Future target changes,
program-policy updates, attachment contents, reviewer independence, and completeness
of the candidate search require the agent's judgment. Preserve these limitations.
