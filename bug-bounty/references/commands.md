# Investigation helper

The installed command is `bug-bounty`. Old `state/pentest/` run paths remain
supported through `--run`; no stored evidence or history is renamed. New runs
use `state/bug-bounty/`, including continuations of finalized legacy runs.

All commands return JSON. Exit 0 means success, 1 means an incomplete check or
failed integrity context, and 2 means invalid input/state. Global `--run RUN`
precedes the subcommand. `--help` on any subcommand lists its required fields.
The helper is stdlib-only and never executes network requests or teardown text.

## Start and plan

```bash
hackbot target show TARGET --json
# Save only its recorded scope text to scope.txt; review program constraints.
bug-bounty init --target TARGET --scope-file scope.txt --owner coordinator \
  --objective 'Resolve the observed boundary discrepancy' --budget-minutes 60
bug-bounty --run RUN add --owner investigator --priority 4 \
  --question 'Can actor A reach an object owned by actor B?' \
  --basis 'Observed object references in an authorized application flow' \
  --prerequisites 'Two researcher-owned accounts and one owned object each' \
  --test 'Compare unchanged baseline with one controlled object-reference change' \
  --supports 'The same authorized flow returns the other owned object without permission' \
  --refutes 'A demonstrated ownership check blocks the altered reference while baseline succeeds'
bug-bounty --run RUN claim --id H-0001 --owner investigator \
  --resource account-A --resource account-B --ttl-minutes 20
```

Claim renewals require the same owner and an unexpired claim. The resource list
must retain every still-used resource. Every worker needing an account mutation,
shared browser profile, listener, or other exclusive resource must claim the
same stable name. Claims apply within a run; coordinate shared resources across
runs manually. Expired claims remain reserved until released or recovered.

`recover --id H-ID --owner coordinator --note TEXT` is allowed only after expiry.
Verify the previous worker has stopped first and record how. Recovery releases
ownership metadata; it does not stop processes, revert state, or clean resources.
For an observation already obtained before your own unrecovered claim expired,
`attempt --late-record ...` saves it without renewing ownership or authorizing
more testing. Once recovered/reassigned, hand the observation to the coordinator.

## Record an attempt

```bash
bug-bounty --run RUN attempt --id H-0001 --owner investigator \
  --identity 'researcher account A' --procedure 'Redacted request references and exact steps' \
  --observation 'Describe the actual response and consequence' \
  --control 'Describe unchanged baseline and contrasting negative control' \
  --outcome supported --next 'Independent reproduction with fresh owned objects' \
  --evidence /path/to/redacted-capture.txt
```

Outcomes are supported/refuted/inconclusive/blocked. All except blocked require
evidence. Blocked records still require the missing prerequisite/recovery step.
Further attempts preserve history and invalidate earlier verification by changing
the hypothesis revision. Do not put live cookies/tokens/passwords in arguments.

Evidence is copied as content-addressed UTF-8 text, limited to 16 MiB/file.
Sensitive directory names, nontext files, empty evidence, symlinks, and common
credential patterns are rejected. This scan is defense in depth, not a guarantee
that text is safe to publish. Keep sensitive originals outside the run. For images,
save a redacted text manifest with image path/hash and manually verify the image;
the current helper validates the manifest bytes, not referenced image content.
For registry captures, remove credential fields/headers entirely and record the
account label separately. The conservative scanner also flags credential fields
whose values have been replaced by placeholders.

## Reproduce independently

```bash
bug-bounty --run RUN packet --id H-0001 --owner coordinator \
  --claim 'Minimal technical claim; attacker capability, operation, expected impact'
# Pass only the returned packet file and required safe fixtures to a fresh verifier.
bug-bounty --run RUN verify --packet V-ID --owner independent-verifier \
  --verdict reproduced --procedure 'Actual fresh reproduction steps' \
  --control 'Baseline and negative comparison actually performed' \
  --note 'Observed impact, limits, and restoration' --evidence fresh-capture.txt
```

Only supported claims get packets. The verifier must not be the original author
or an attempt owner. A current reproduced verdict requires fresh evidence bytes;
merely copying old capture files is rejected. These are record-level safeguards,
not authentication or proof the operator genuinely used a separate session.
The packet freezes the claim revision and scope snapshot; later attempts or
changed evidence invalidate its use. Review output appends separately.

## Resource cleanup and completion

```bash
bug-bounty --run RUN resource add --name listener-unique-id --owner investigator \
  --note 'Exact owned identifier and teardown procedure; do not execute automatically'
bug-bounty --run RUN resource clean --name listener-unique-id --owner investigator \
  --note 'Stopped exact owned resource and verified absence' --evidence cleanup.txt
bug-bounty --run RUN release --id H-0001 --owner investigator --note 'Work stopped; changes restored'
bug-bounty --run RUN check
bug-bounty --run RUN finish --owner coordinator --status completed --note 'Reconciled and independently reproduced'
```

Register every temporary process, listener, remote object, or reversible mutation
that needs cleanup. Completion and partial handoff both require released claims,
verified registered cleanup, and intact evidence. A budget expiry blocks new
claims, but saving evidence, recording a blocker, review, and cleanup remain
available. `next` reports the remaining time; it never sends a request.

Run metadata is limited to 2 MiB, with 512 KiB reserved for cleanup, release,
recovery, and finish records. Runs support up to 32 simultaneous claims and 32
registered cleanup resources; lifecycle notes are limited to 1000 characters.
When normal growth reaches its limit, clean up and finish partial before starting
a linked continuation. Tool output above 32 KB is saved below
`RUN/outputs/` and replaced by a file reference. `context --limit N` and
`next --limit N` paginate the summary (up to 50 items); use `--offset N` for
later pages and `show` for detail.
The summary sorts priority then stable ID; the agent must account for prerequisites
and claims before acting. Context reconstruction fails closed on bad evidence.

The application preserves attempt/events through its CLI; local filesystem
writers can edit them. The run is not a tamper-proof audit log. Failed multi-file
operations can leave unreferenced content-addressed evidence or packet files;
these do not count as proof and are never deleted automatically. Run state is
gitignored by the setup; review/redact a separate report before committing it.

For a finalized partial/blocked run, start a new run with current scope and
`init ... --parent-run OLD_RUN`. Its context points to the frozen parent snapshot.
Review the parent's open items with `context`/`show`, create explicitly linked
hypotheses in the new run, and keep old evidence/history intact. Budgets and
authorization do not automatically reset or expand; agree a continuation budget
within the engagement's existing limits.

The [extended workflow](workflow.md) adds access, browser-flow, prerequisite,
triage, and duplicate-review records. `check`/`finish` concern investigation
completion; `ready --id H-ID --report FILE` separately checks a report's readiness.
