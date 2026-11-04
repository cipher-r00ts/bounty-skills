#!/usr/bin/env python3
"""Offline bug bounty investigation memory. No network requests or shell execution."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid
from types import SimpleNamespace

MAX_BYTES = 2 * 1024 * 1024
LIFECYCLE_RESERVE = 512 * 1024
MAX_EVIDENCE = 16 * 1024 * 1024
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\bAKIA[A-Z0-9]{16}\b|\bgh[pousr]_[A-Za-z0-9]{20,}|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|"
    r"(?i:authorization[\"']?\s*:\s*[\"']?(?:bearer|basic)\s+\S+|"
    r"(?:cookie|set-cookie)[\"']?\s*:\s*[\"']?\S+|"
    r"(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)[\"']?\s*[=:]\s*[\"']?\S+)"
)
_WORKFLOW = None


def workflow_module():
    global _WORKFLOW
    if _WORKFLOW is None:
        spec = importlib.util.spec_from_file_location("bug_bounty_workflow", Path(__file__).resolve().with_name("workflow.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _WORKFLOW = module
    return _WORKFLOW


def investigators(h):
    return {h["author"], *(x["owner"] for x in h["attempts"]),
            *(x["owner"] for x in h.get("conditions", []))}


def now():
    return datetime.now(timezone.utc)


def stamp():
    return now().isoformat(timespec="seconds")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def safe_text(text):
    require(isinstance(text, str) and text.strip(), "nonempty text required")
    require(len(text) <= 12000, "text exceeds 12000 characters; use an evidence file")
    require(not contains_secret(text), "possible secret rejected; use a redacted derivative")
    return text.strip()


def label(text):
    text = safe_text(text)
    require(len(text) <= 120, "owner/resource label exceeds 120 characters")
    return text


def contains_secret(text):
    if SECRET.search(text):
        return True
    # Decode escaped JSON keys/values rather than relying on their serialized form.
    try:
        decoded = json.dumps(json.loads(text), ensure_ascii=False)
    except (ValueError, RecursionError):
        return False
    return bool(SECRET.search(decoded))


def read_bytes(path, limit=MAX_BYTES):
    with Path(path).open("rb") as handle:
        data = handle.read(limit + 1)
    require(len(data) <= limit, "input exceeds size limit")
    return data


def atomic(path, value):
    data = encode(value) + b"\n"
    require(len(data) <= MAX_BYTES, "run is full; finish it and start a linked run")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def confined(base, relative):
    relative = Path(relative)
    require(not relative.is_absolute(), "managed path must be relative")
    path = (base / relative).resolve()
    require(path.is_relative_to(base.resolve()), "path escapes run directory")
    return path


def event(state, kind, owner, data):
    state["events"].append({"sequence": len(state["events"]) + 1,
                            "at": stamp(), "kind": kind, "owner": owner,
                            "data": json.loads(encode(data))})


@contextmanager
def transaction(run, write=True, lifecycle=False):
    run = Path(run).resolve()
    require(run.is_dir() and (run / "run.json").is_file(), "run not initialized")
    with (run / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        state = json.loads(read_bytes(confined(run, "run.json")))
        require(state.get("version") == 1, "unsupported run schema")
        require(state.get("run_id") == run.name, "run directory identity mismatch")
        yield run, state
        if write:
            require(lifecycle or len(encode(state)) + 1 <= MAX_BYTES - LIFECYCLE_RESERVE,
                    "run growth limit reached; cleanup and finish partial, then start a linked run")
            atomic(confined(run, "run.json"), state)


def hypothesis(state, identifier):
    require(identifier in state["hypotheses"], "unknown hypothesis")
    return state["hypotheses"][identifier]


def revision(h):
    return digest(h)


def alive(claim):
    return datetime.fromisoformat(claim["expires_at"]) > now()


def writable(state):
    require(state["status"] == "active", "run is finished; start a new linked run")


def owned(state, identifier, owner, late_record=False):
    writable(state)
    claim = state["claims"].get(identifier)
    require(claim and claim["owner"] == owner and (alive(claim) or late_record),
            "own claim required; an expired unrecovered claim needs --late-record to save observations only")


def evidence(run, paths):
    require(len(paths) <= 8, "maximum eight evidence files per record")
    results = []
    for name in paths:
        src = Path(name).expanduser().absolute()
        require(not any(p.is_symlink() for p in (src, *src.parents)),
                "evidence path must not contain symlinks")
        src = src.resolve()
        require(src.is_file(), "evidence must be a regular file")
        require(not any(p.lower() in {"sensitive", "secrets", "registration"} for p in src.parts),
                "sensitive evidence paths are prohibited; use a redacted derivative")
        require(src.suffix.lower() in {".txt", ".md", ".json", ".jsonl", ".http", ".log", ".csv"},
                "only redacted UTF-8 text evidence is supported; reference screenshots in a text manifest")
        data = read_bytes(src, MAX_EVIDENCE)
        text = data.decode("utf-8")
        require(text.strip(), "empty evidence")
        require(not contains_secret(text), "possible secret in evidence; redact before registering")
        sha = hashlib.sha256(data).hexdigest()
        rel = f"evidence/{sha}.txt"
        dest = confined(run, rel)
        dest.parent.mkdir(exist_ok=True)
        if dest.exists():
            require(hashlib.sha256(read_bytes(dest, MAX_EVIDENCE)).hexdigest() == sha,
                    "existing evidence is corrupt")
        else:
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        results.append({"path": rel, "sha256": sha, "bytes": len(data)})
    return results


def integrity(run, state):
    errors = []
    references = [{"path": "scope.txt", "sha256": state["scope_sha256"]}]
    for h in state["hypotheses"].values():
        for attempt in h["attempts"]:
            references.extend(attempt["evidence"])
    for packet in state["packets"].values():
        references.append({"path": packet["path"], "sha256": packet["sha256"]})
    for review in state["reviews"]:
        references.extend(review["evidence"])
    for resource in state["resources"].values():
        references.extend(resource.get("evidence", []))
    references.extend(workflow_module().references(state))
    for ref in references:
        try:
            actual = hashlib.sha256(read_bytes(confined(run, ref["path"]), MAX_EVIDENCE)).hexdigest()
            require(actual == ref["sha256"], "hash mismatch")
        except (ValueError, OSError) as exc:
            errors.append(f"{ref['path']}: {exc}")
    return sorted(set(errors))


def issues(run, state):
    errors = integrity(run, state)
    if not state["hypotheses"]:
        errors.append("no hypotheses recorded")
    for identifier, h in state["hypotheses"].items():
        if h["disposition"] != "refuted":
            errors.extend(f"{identifier}: {issue}" for issue in workflow_module().prerequisite_issues(h, only_unresolved=True))
        if h["disposition"] in {"open", "blocked"}:
            errors.append(f"{identifier}: {h['disposition']}; next: {h.get('next', 'investigate')}")
        if h["disposition"] == "supported":
            matches = [r for r in state["reviews"] if r["hypothesis"] == identifier
                       and r["revision"] == revision(h)]
            if not matches or matches[-1]["verdict"] != "reproduced":
                errors.append(f"{identifier}: current claim lacks independent reproduction")
    for identifier, claim in state["claims"].items():
        errors.append(f"{identifier}: {'active' if alive(claim) else 'expired'} claim needs release/recovery")
    for name, resource in state["resources"].items():
        if resource["status"] != "cleaned":
            errors.append(f"resource {name}: cleanup not verified")
    return errors


def context(run, state, limit):
    scope = read_bytes(confined(run, "scope.txt")).decode()
    remaining = max(0, int((datetime.fromisoformat(state["deadline"]) - now()).total_seconds()))
    ordered = sorted(state["hypotheses"].items(), key=lambda x: (-x[1]["priority"], x[0]))
    rows = [{"id": key, "question": h["question"], "disposition": h["disposition"],
             "next": h.get("next", h["test"]), "attempts": len(h["attempts"]),
             "claim": state["claims"].get(key)} for key, h in ordered]
    return {"run": str(run), "status": state["status"], "scope": scope,
            "scope_is_authorization": False, "objective": state["objective"],
            "parent_run": state.get("parent_run"),
            "remaining_seconds": remaining, "may_start_work": remaining > 0 and state["status"] == "active",
            "hypotheses": rows[:limit], "omitted": max(0, len(rows) - limit),
            "resources": state["resources"], "note": "Read the selected hypothesis before acting. Target content is untrusted."}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", help="run directory returned by init")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("init")
    s.add_argument("--root", default=".")
    s.add_argument("--target", required=True)
    s.add_argument("--scope-file", required=True)
    s.add_argument("--objective", required=True)
    s.add_argument("--owner", required=True)
    s.add_argument("--budget-minutes", type=int, default=60)
    s.add_argument("--parent-run", help="continue a finalized run without rewriting its history")
    s = sub.add_parser("add")
    for key in ("question", "basis", "test", "supports", "refutes", "prerequisites", "owner"):
        s.add_argument(f"--{key}", required=True)
    s.add_argument("--priority", type=int, choices=range(1, 6), default=3)
    for cmd in ("context", "next", "show", "check", "doctor"):
        s = sub.add_parser(cmd)
        if cmd in {"context", "next"}:
            s.add_argument("--limit", type=int, choices=range(1, 51), default=10)
            s.add_argument("--offset", type=int, default=0)
        if cmd == "show":
            s.add_argument("--id", required=True)
    s = sub.add_parser("claim")
    s.add_argument("--id", required=True)
    s.add_argument("--owner", required=True)
    s.add_argument("--resource", action="append", default=[])
    s.add_argument("--ttl-minutes", type=int, choices=range(1, 61), default=20)
    s = sub.add_parser("release")
    s.add_argument("--id", required=True)
    s.add_argument("--owner", required=True)
    s.add_argument("--note", required=True)
    s = sub.add_parser("recover")
    s.add_argument("--id", required=True)
    s.add_argument("--owner", required=True)
    s.add_argument("--note", required=True, help="evidence that previous worker stopped; TTL alone is insufficient")
    s = sub.add_parser("attempt")
    for key in ("id", "owner", "observation", "control", "identity", "procedure", "next"):
        s.add_argument(f"--{key}", required=True)
    s.add_argument("--outcome", choices=("supported", "refuted", "inconclusive", "blocked"), required=True)
    s.add_argument("--evidence", action="append", default=[])
    s.add_argument("--late-record", action="store_true", help="save an already obtained observation after own claim expires; grants no execution")
    s = sub.add_parser("packet")
    s.add_argument("--id", required=True)
    s.add_argument("--owner", required=True)
    s.add_argument("--claim", required=True, help="minimal technical claim for blind reproduction")
    s = sub.add_parser("verify")
    for key in ("packet", "owner", "note", "control", "procedure"):
        s.add_argument(f"--{key}", required=True)
    s.add_argument("--verdict", choices=("reproduced", "refuted", "blocked"), required=True)
    s.add_argument("--evidence", action="append", default=[])
    s = sub.add_parser("resource")
    s.add_argument("action", choices=("add", "clean"))
    for key in ("name", "owner", "note"):
        s.add_argument(f"--{key}", required=True)
    s.add_argument("--evidence", action="append", default=[])
    s = sub.add_parser("finish")
    s.add_argument("--owner", required=True)
    s.add_argument("--note", required=True)
    s.add_argument("--status", choices=("completed", "partial", "blocked", "aborted"), required=True)
    workflow_module().register(sub)
    return p


def execute(a):
    if a.command == "doctor":
        return {"tools": {name: shutil.which(name) for name in
                          ("python3", "hackbot", "node", "curl", "agent-browser", "httpx", "ffuf", "katana")},
                "note": "PATH presence only; no credentials inspected and no target contacted"}, 0
    if a.command == "init":
        require(NAME.fullmatch(a.target), "invalid target name")
        require(1 <= a.budget_minutes <= 1440, "budget must be 1..1440 minutes")
        base = Path(a.root).resolve()
        target = (base / "targets" / a.target).resolve()
        require(target.is_relative_to(base) and target.is_dir(), "existing target directory required")
        scope = read_bytes(a.scope_file).decode()
        require(len(scope) <= 12000, "scope exceeds context limit")
        safe_text(scope)
        owner, objective = label(a.owner), safe_text(a.objective)
        directory = (target / "state" / "bug-bounty").resolve()
        require(directory.is_relative_to(target), "state directory escapes target")
        parent = None
        if a.parent_run:
            parent_path = Path(a.parent_run).resolve()
            legacy_directory = (target / "state" / "pentest").resolve()
            require(legacy_directory.is_relative_to(target), "legacy state directory escapes target")
            require(parent_path.is_relative_to(directory) or parent_path.is_relative_to(legacy_directory),
                    "parent must belong to the same target")
            with transaction(parent_path, write=False) as (_, previous):
                require(previous["target"] == a.target and previous["status"] != "active",
                        "parent must be a finalized run of this target")
                parent = {"path": str(parent_path), "run_id": previous["run_id"], "snapshot_sha256": digest(previous)}
        run = directory / (now().strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
        run.mkdir(parents=True, mode=0o700)
        (run / "scope.txt").write_text(scope)
        state = {"version": 1, "run_id": run.name, "target": a.target, "objective": objective,
                 "owner": owner, "created_at": stamp(), "deadline": (now() + timedelta(minutes=a.budget_minutes)).isoformat(),
                 "scope_sha256": hashlib.sha256(scope.encode()).hexdigest(), "status": "active",
                 "parent_run": parent,
                 "workflow": workflow_module().empty(),
                 "hypotheses": {}, "claims": {}, "resources": {}, "packets": {}, "reviews": [], "events": []}
        event(state, "initialized", owner, {"objective": objective})
        atomic(run / "run.json", state)
        return {"run": str(run), "status": "active", "note": "Scope snapshot is context, not an authorization grant."}, 0
    require(a.run, "--run is required")
    readonly = a.command in {"context", "next", "show", "check", "ready"}
    lifecycle = a.command in {"release", "recover", "finish"} or a.command == "resource" and a.action == "clean"
    with transaction(a.run, write=not readonly, lifecycle=lifecycle) as (run, state):
        if a.command in {"context", "next"}:
            require(a.offset >= 0, "offset must be nonnegative")
            errors = integrity(run, state)
            if errors:
                return {"may_start_work": False, "integrity_errors": errors}, 1
            result = context(run, state, a.limit)
            # Pagination applies to the full deterministic summary, not a pre-sliced list.
            full = context(run, state, len(state["hypotheses"]))
            result["hypotheses"] = full["hypotheses"][a.offset:a.offset + a.limit]
            result["offset"] = a.offset
            result["omitted"] = max(0, len(full["hypotheses"]) - a.offset - a.limit)
            result["workflow"] = workflow_module().summary(state)
            if a.command == "next":
                queue = []
                for identifier, h in sorted(state["hypotheses"].items(), key=lambda x: (-x[1]["priority"], x[0])):
                    if h["disposition"] == "refuted":
                        continue
                    if h["disposition"] == "supported":
                        reviews = [r for r in state["reviews"] if r["hypothesis"] == identifier and r["revision"] == revision(h)]
                        if workflow_module().prerequisite_issues(h):
                            action = "resolve_attacker_prerequisites"
                        elif reviews and reviews[-1]["verdict"] == "reproduced":
                            action = workflow_module().next_action(state, identifier, SimpleNamespace(**globals()))
                            if action is None:
                                continue
                        else:
                            action = "independent_reproduction" if not reviews else "resolve_verifier_objection"
                    else:
                        action = "unblock" if h["disposition"] == "blocked" else "investigate"
                    queue.append({"id": identifier, "action": action, "priority": h["priority"],
                                  "next": h.get("next", h["test"]), "claim": state["claims"].get(identifier)})
                result["queue"] = queue[a.offset:a.offset + a.limit]
                result["queue_omitted"] = max(0, len(queue) - a.offset - a.limit)
            return result, 0
        if a.command == "show":
            return hypothesis(state, a.id), 0
        if a.command == "check":
            errors = issues(run, state)
            return {"complete": not errors, "issues": errors, "status": state["status"],
                    "note": "Investigation completion only; use ready --id H-ID --report FILE for report readiness."}, 1 if errors else 0
        if a.command == "ready":
            return workflow_module().handle(a, run, state, SimpleNamespace(**globals()))
        writable(state)
        owner = label(a.owner)
        if lifecycle:
            require(len(a.note) <= 1000, "lifecycle note exceeds 1000 characters")
        if a.command in workflow_module().COMMANDS:
            return workflow_module().handle(a, run, state, SimpleNamespace(**globals()))
        if a.command == "add":
            identifier = f"H-{len(state['hypotheses']) + 1:04d}"
            h = {key: safe_text(getattr(a, key)) for key in
                 ("question", "basis", "test", "supports", "refutes", "prerequisites")}
            h.update(author=owner, priority=a.priority, disposition="open", attempts=[])
            state["hypotheses"][identifier] = h
            event(state, "hypothesis_added", owner, {"id": identifier, **h})
            return {"id": identifier}, 0
        if a.command == "claim":
            hypothesis(state, a.id)
            require(not integrity(run, state), "evidence integrity failed")
            require(now() < datetime.fromisoformat(state["deadline"]), "budget expired; save handoff and finish partial")
            current = state["claims"].get(a.id)
            require(current or len(state["claims"]) < 32, "maximum 32 simultaneous claims per run")
            require(not current or current["owner"] == owner and alive(current), "claim exists; release or recover it first")
            resources = sorted(set(label(r) for r in a.resource))
            require(len(resources) <= 32, "maximum 32 resources per claim")
            require(not current or set(current["resources"]).issubset(resources),
                    "renewal cannot drop resources; release after stopping work before changing ownership")
            for identifier, c in state["claims"].items():
                if identifier != a.id:
                    require(not set(resources).intersection(c["resources"]),
                            "resource claimed by another task; expired claims require explicit recovery")
            claim = {"owner": owner, "resources": resources,
                     "expires_at": (now() + timedelta(minutes=a.ttl_minutes)).isoformat()}
            state["claims"][a.id] = claim
            event(state, "claimed", owner, {"id": a.id, **claim})
            return claim, 0
        if a.command in {"release", "recover"}:
            require(a.id in state["claims"], "no claim to release")
            c = state["claims"][a.id]
            if a.command == "release":
                require(c["owner"] == owner, "only claim owner can release")
            else:
                require(not alive(c), "cannot recover an unexpired claim")
            event(state, a.command, owner, {"id": a.id, "previous": c, "note": safe_text(a.note)})
            del state["claims"][a.id]
            return {"released": a.id}, 0
        if a.command == "attempt":
            owned(state, a.id, owner, a.late_record)
            h = hypothesis(state, a.id)
            require(a.evidence or a.outcome == "blocked", "observed outcomes require evidence")
            attempt = {key: safe_text(getattr(a, key)) for key in
                       ("observation", "control", "identity", "procedure", "next")}
            attempt.update(owner=owner, at=stamp(), outcome=a.outcome, evidence=evidence(run, a.evidence),
                           late_record=not alive(state["claims"][a.id]))
            h["attempts"].append(attempt)
            h["disposition"] = {"inconclusive": "open"}.get(a.outcome, a.outcome)
            h["next"] = attempt["next"]
            event(state, "attempt", owner, {"id": a.id, **attempt})
            return {"id": a.id, "disposition": h["disposition"], "revision": revision(h)}, 0
        if a.command == "packet":
            h = hypothesis(state, a.id)
            require(h["disposition"] == "supported", "only a supported claim enters reproduction")
            require(not integrity(run, state), "evidence integrity failed")
            key = "V-" + uuid.uuid4().hex[:12]
            packet = {"version": 1, "packet": key, "hypothesis": a.id,
                      "claim": safe_text(a.claim), "prerequisites": h["prerequisites"],
                      "attacker_prerequisites": [{key: row[key] for key in ("name", "state", "attacker_path", "evidence")}
                                                for row in workflow_module().conditions(h).values()],
                      "scope": read_bytes(confined(run, "scope.txt")).decode(),
                      "revision": revision(h), "scope_sha256": state["scope_sha256"],
                      "instructions": "Independently reproduce with fresh observations and controls; do not read run.json or investigation transcripts. Record exact procedure, limitations and cleanup."}
            rel = f"packets/{key}.json"
            atomic(confined(run, rel), packet)
            state["packets"][key] = {"path": rel, "sha256": hashlib.sha256(read_bytes(run / rel)).hexdigest(),
                                      "hypothesis": a.id, "revision": revision(h)}
            event(state, "packet_created", owner, {"packet": key, "id": a.id})
            return {"packet": key, "path": str(run / rel), "note": "Give only this packet to a fresh verifier."}, 0
        if a.command == "verify":
            require(a.packet in state["packets"], "unknown verification packet")
            require(not integrity(run, state), "evidence or packet integrity failed")
            packet = state["packets"][a.packet]
            h = hypothesis(state, packet["hypothesis"])
            require(revision(h) == packet["revision"], "claim changed; create a fresh packet")
            require(owner not in investigators(h), "verifier must differ from investigator")
            require(a.evidence or a.verdict == "blocked", "verification requires fresh evidence")
            refs = evidence(run, a.evidence)
            old = {r["sha256"] for t in h["attempts"] for r in t["evidence"]}
            require(a.verdict == "blocked" or any(r["sha256"] not in old for r in refs),
                    "verification must include a fresh capture, not only copied investigation evidence")
            review = {key: safe_text(getattr(a, key)) for key in ("note", "control", "procedure")}
            review.update(hypothesis=packet["hypothesis"], revision=packet["revision"],
                          packet=a.packet, owner=owner, verdict=a.verdict, evidence=refs, at=stamp())
            state["reviews"].append(review)
            event(state, "verification", owner, review)
            return {"recorded": True, "verdict": a.verdict}, 0
        if a.command == "resource":
            name, note = label(a.name), safe_text(a.note)
            if a.action == "add":
                require(len(state["resources"]) < 32, "maximum 32 cleanup resources per run; use a linked run")
                require(name not in state["resources"], "resource already registered; use a new unique name")
                state["resources"][name] = {"owner": owner, "status": "active", "teardown": note, "evidence": []}
            else:
                require(name in state["resources"], "unknown resource")
                r = state["resources"][name]
                require(r["owner"] == owner, "only resource owner can record cleanup")
                require(a.evidence, "cleanup verification requires evidence")
                r.update(status="cleaned", note=note, evidence=evidence(run, a.evidence))
            event(state, "resource_" + a.action, owner, {"name": name, "note": note})
            return state["resources"][name], 0
        if a.command == "finish":
            errors = issues(run, state)
            require(not integrity(run, state), "cannot finish with corrupt evidence")
            require(not state["claims"], "release/recover claims before finishing")
            require(all(r["status"] == "cleaned" for r in state["resources"].values()), "cleanup incomplete")
            require(a.status != "completed" or not errors, "completion blocked: " + "; ".join(errors))
            state["status"] = a.status
            event(state, "finished", owner, {"status": a.status, "note": safe_text(a.note),
                  "open_items": [e[:400] for e in errors[:50]], "omitted_open_items": max(0, len(errors) - 50)})
            return {"status": a.status, "open_items": errors}, 0
    raise ValueError("unsupported command")


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        result, code = execute(args)
        output = {"ok": code == 0, "data": result}
        if len(encode(output)) > 32000 and args.run:
            run = Path(args.run).resolve()
            path = confined(run, f"outputs/{uuid.uuid4().hex}.json")
            atomic(path, output)
            output = {"ok": code == 0, "data": {"stored_output": str(path),
                      "bytes": len(encode(output)), "note": "Read relevant bounded portions of the saved output."}}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return code
    except (ValueError, OSError, KeyError, TypeError) as exc:
        # Do not echo argument values, paths from external errors, or secret-bearing input.
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else "invalid or inaccessible run/input"
        print(json.dumps({"ok": False, "error": {"code": "INVALID_STATE", "message": message[:1000]}}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
