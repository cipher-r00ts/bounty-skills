import json
from pathlib import Path
import unittest

import test_bug_bounty as base


class WorkflowTest(unittest.TestCase):
    setUp = base.InvestigationTest.setUp
    tearDown = base.InvestigationTest.tearDown
    invoke = base.InvestigationTest.invoke
    call = base.InvestigationTest.call
    add = base.InvestigationTest.add
    claim = base.InvestigationTest.claim
    attempt = base.InvestigationTest.attempt
    supported = base.InvestigationTest.supported
    packet = base.InvestigationTest.packet
    review = base.InvestigationTest.review
    state = base.InvestigationTest.state
    change_state = base.InvestigationTest.change_state

    def report(self, name="current.md", body="Owned-boundary test report with actual fixture limits"):
        path = self.root / "targets/demo" / name
        path.write_text(body)
        return path

    def reproduce(self, identifier):
        self.review(self.packet(identifier))

    def triage(self, identifier, report, owner="triager", verdict="pass", code=0):
        return self.call("triage", "--id", identifier, "--owner", owner, "--report", report,
                         "--verdict", verdict, "--impact", "Observed cross-owned boundary effect",
                         "--attacker-path", "Attacker-owned account obtains reference from permitted listing",
                         "--business-intent", "Documented owner-only policy compared with observed flow",
                         "--limits", "Local synthetic fixture only", "--note", "Exact existing claim evaluated",
                         "--evidence", self.fresh, code=code)

    def dedupe_packet(self, identifier, candidates=()):
        args = ["dedupe-packet", "--id", identifier, "--owner", "controller"]
        for path in candidates:
            args += ["--candidate", path]
        if not candidates:
            args += ["--empty-reason", "Searched fixture target reports; none besides current claim"]
        return self.call(*args)

    def compare(self, packet, verdict="distinct", material="none", facts=None, code=0, rows=None):
        manifest = json.loads(Path(packet["path"]).read_text())
        if rows is None:
            rows = [{"candidate": c["candidate"], "verdict": verdict,
                     "rationale": "Compared the boundary, acquisition path and remediation",
                     "material": material, "facts": facts or []} for c in manifest["candidates"]]
        path = self.root / "comparison.json"
        path.write_text(json.dumps(rows))
        return self.call("dedupe-review", "--packet", packet["packet"], "--owner", "deduper",
                         "--results-file", path, "--note", "Full supplied manifest reviewed offline", code=code)

    def release(self, identifier):
        self.call("release", "--id", identifier, "--owner", "finder", "--note", "Stopped and restored")

    def condition(self, identifier, state="reachable", evidence=True, code=0):
        args = ["prerequisite", "--id", identifier, "--name", "reference-acquisition",
                "--state", state, "--attacker-path", "Researcher A public listing with a contrasting control",
                "--note", "Concrete observation and bounded search limits", "--owner", "finder"]
        if evidence:
            args += ["--evidence", self.capture]
        return self.call(*args, code=code)

    def test_access_and_walk_are_durable_context(self):
        self.call("access", "--account", "A", "--role", "member", "--state", "usable",
                  "--capability", "Login and owned-object creation observed", "--owner", "controller", code=2)
        self.call("access", "--account", "A", "--role", "member", "--state", "usable",
                  "--capability", "Login and owned-object creation observed", "--owner", "controller",
                  "--evidence", self.capture)
        identifier = self.add()
        self.call("walk", "--flow", "Owned item sharing", "--owner", "controller", "--hypothesis", identifier,
                  "--observation", "Cross-origin transition captured", "--evidence", self.fresh)
        summary = self.call("context")["workflow"]
        self.assertEqual(summary["access"][0]["account"], "A")
        self.assertEqual(summary["walk_observations"], 1)
        self.call("access", "--account", "A", "--role", "member", "--state", "unavailable",
                  "--capability", "Session expired; reacquire owned access", "--owner", "controller")
        self.assertEqual(self.call("context")["workflow"]["access"][0]["state"], "unavailable")

    def test_prerequisite_blocks_readiness_and_invalidates_old_reproduction(self):
        identifier = self.supported()
        old_packet = self.packet(identifier)
        self.condition(identifier, "blocked", evidence=False)
        self.assertEqual(self.call("next")["queue"][0]["action"], "resolve_attacker_prerequisites")
        self.review(old_packet, code=2)
        self.condition(identifier, "reachable", evidence=False, code=2)
        self.condition(identifier)
        self.reproduce(identifier)
        self.assertEqual(len(self.state()["hypotheses"][identifier]["conditions"]), 2)

    def test_complete_report_readiness_pipeline(self):
        identifier = self.supported()
        self.condition(identifier)
        self.reproduce(identifier)
        report = self.report()
        self.assertFalse(self.call("ready", "--id", identifier, "--report", report, code=1)["ready"])
        self.triage(identifier, report)
        self.assertEqual(self.call("next")["queue"][0]["action"], "duplicate_review")
        packet = self.dedupe_packet(identifier, [self.report("historical.md", "Different boundary and separate fix")])
        self.compare(packet)
        self.release(identifier)
        self.assertTrue(self.call("ready", "--id", identifier, "--report", report)["ready"])
        self.assertEqual(self.call("next")["queue"], [])
        self.call("finish", "--owner", "controller", "--status", "completed", "--note", "Fixture pipeline done")
        self.assertTrue(self.call("ready", "--id", identifier, "--report", report)["ready"])

    def test_empty_manifest_requires_reason_and_explicit_review(self):
        identifier = self.supported()
        self.reproduce(identifier)
        report = self.report()
        self.triage(identifier, report)
        self.call("dedupe-packet", "--id", identifier, "--owner", "controller", code=2)
        packet = self.dedupe_packet(identifier)
        self.release(identifier)
        self.call("ready", "--id", identifier, "--report", report, code=1)
        self.compare(packet)
        self.call("ready", "--id", identifier, "--report", report)

    def test_same_investigator_cannot_triage(self):
        identifier = self.supported()
        self.reproduce(identifier)
        self.triage(identifier, self.report(), owner="finder", code=2)

    def test_triage_pass_requires_proof_and_prerequisites(self):
        identifier = self.supported()
        report = self.report()
        self.triage(identifier, report, code=2)
        self.condition(identifier, "unreachable")
        self.reproduce(identifier)
        self.triage(identifier, report, code=2)
        self.triage(identifier, report, verdict="needs-evidence")

    def test_report_edits_and_later_objections_invalidate_readiness(self):
        identifier = self.supported()
        self.reproduce(identifier)
        report = self.report()
        self.triage(identifier, report)
        self.compare(self.dedupe_packet(identifier))
        self.release(identifier)
        report.write_text("Modified technical claim")
        self.call("ready", "--id", identifier, "--report", report, code=1)
        self.triage(identifier, report, verdict="rejected")
        self.call("ready", "--id", identifier, "--report", report, code=1)

    def test_new_reproduction_invalidates_previous_triage_and_duplicate_review(self):
        identifier = self.supported()
        packet = self.packet(identifier)
        self.review(packet)
        report = self.report()
        self.triage(identifier, report)
        self.compare(self.dedupe_packet(identifier))
        self.review(packet, verdict="blocked")
        self.call("ready", "--id", identifier, "--report", report, code=1)

    def test_every_candidate_reviewed_and_uncertain_duplicate_blocks(self):
        identifier = self.supported()
        self.reproduce(identifier)
        report = self.report()
        self.triage(identifier, report)
        packet = self.dedupe_packet(identifier, [self.report("old.md", "Related prior defect")])
        self.compare(packet, rows=[], code=2)
        self.compare(packet, verdict="possible_duplicate", material="strengthens", code=2)
        self.compare(packet, verdict="possible_duplicate", material="strengthens", facts=["New proven attacker delivery"])
        self.release(identifier)
        self.call("ready", "--id", identifier, "--report", report, code=1)
        self.assertEqual(self.call("next")["queue"][0]["action"], "resolve_possible_duplicate")

    def test_expanded_manifest_invalidates_earlier_distinct_decision(self):
        identifier = self.supported()
        self.reproduce(identifier)
        report = self.report()
        self.triage(identifier, report)
        old = self.dedupe_packet(identifier)
        self.compare(old)
        newest = self.dedupe_packet(identifier, [self.report("old.md", "New candidate requiring comparison")])
        self.compare(old, code=2)
        self.release(identifier)
        self.call("ready", "--id", identifier, "--report", report, code=1)
        self.compare(newest)
        self.call("ready", "--id", identifier, "--report", report)

    def test_known_duplicate_cannot_be_hidden_by_empty_replacement_manifest(self):
        identifier = self.supported()
        self.reproduce(identifier)
        report = self.report()
        self.triage(identifier, report)
        old = self.dedupe_packet(identifier, [self.report("related.md", "Prior report sharing control")])
        self.compare(old, verdict="possible_duplicate")
        self.call("dedupe-packet", "--id", identifier, "--owner", "controller",
                  "--empty-reason", "Omitting prior candidate is not a resolution", code=2)
        self.triage(identifier, report)
        self.call("dedupe-packet", "--id", identifier, "--owner", "controller",
                  "--empty-reason", "New triage cannot hide prior candidate", code=2)

    def test_prerequisite_late_record_after_claim_and_budget_expiry(self):
        identifier = self.add()
        self.claim(identifier)
        state = self.state()
        state["deadline"] = "2000-01-01T00:00:00+00:00"
        state["claims"][identifier]["expires_at"] = state["deadline"]
        self.change_state(state)
        self.condition(identifier, state="blocked", evidence=False, code=2)
        self.call("prerequisite", "--id", identifier, "--name", "access", "--state", "blocked",
                  "--attacker-path", "Required role unavailable", "--note", "Previously observed blocker only",
                  "--owner", "finder", "--late-record")
        self.assertTrue(self.state()["hypotheses"][identifier]["conditions"][0]["late_record"])

    def test_candidates_confined_to_same_target_and_frozen(self):
        identifier = self.supported()
        self.reproduce(identifier)
        self.triage(identifier, self.report())
        self.call("dedupe-packet", "--id", identifier, "--owner", "controller", "--candidate", self.capture, code=2)
        candidate = self.report("prior.md", "Original historic report")
        packet = self.dedupe_packet(identifier, [candidate])
        candidate.write_text("Updated outside frozen packet")
        self.compare(packet)
        manifest = json.loads(Path(packet["path"]).read_text())
        (self.run / manifest["candidates"][0]["path"]).write_text("Tampered snapshot")
        self.call("context", code=1)

    def test_v1_run_without_workflow_keys_still_reads_and_writes(self):
        state = self.state()
        del state["workflow"]
        self.change_state(state)
        self.call("context")
        self.call("access", "--account", "A", "--role", "member", "--state", "partial",
                  "--capability", "Existing session needs refresh", "--owner", "controller")
        self.assertEqual(len(self.state()["workflow"]["access"]), 1)


if __name__ == "__main__":
    unittest.main()
