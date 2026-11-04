from concurrent.futures import ThreadPoolExecutor
import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/bug_bounty.py"
INSTALL = SCRIPT.with_name("install.py")


class InvestigationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "targets/demo").mkdir(parents=True)
        self.scope = self.root / "scope.txt"
        self.scope.write_text("http://127.0.0.1:8000 - controlled fixture only\n")
        self.run = None
        self.run = Path(self.call("init", "--root", self.root, "--target", "demo", "--scope-file", self.scope,
                                  "--owner", "controller", "--objective", "Investigate local fixture")["run"])
        self.capture = self.root / "capture.txt"
        self.capture.write_text("baseline owned object A; changed reference returns owned object B\n")
        self.fresh = self.root / "fresh.txt"
        self.fresh.write_text("fresh reproduction using newly created owned fixtures C and D\n")

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, *args, run=None):
        prefix = [sys.executable, str(SCRIPT)]
        if self.run and args[0] not in {"init", "doctor"}:
            prefix += ["--run", str(run or self.run)]
        return subprocess.run([*prefix, *map(str, args)], capture_output=True, text=True)

    def call(self, *args, code=0):
        result = self.invoke(*args)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        obj = json.loads(result.stdout)
        return obj.get("data", obj.get("error"))

    def add(self):
        return self.call("add", "--owner", "finder", "--question", "Can A cross an object boundary?",
                         "--basis", "Observed owned references", "--prerequisites", "Two owned accounts",
                         "--test", "Change one owned reference", "--supports", "Other object returned",
                         "--refutes", "Ownership enforced")["id"]

    def claim(self, identifier, owner="finder", resource="account-A", code=0):
        return self.call("claim", "--id", identifier, "--owner", owner, "--resource", resource, code=code)

    def attempt(self, identifier, outcome="supported", evidence=None, code=0):
        args = ["attempt", "--id", identifier, "--owner", "finder", "--identity", "researcher A",
                "--procedure", "Compare redacted fixture requests", "--observation", "Observed boundary effect",
                "--control", "Baseline succeeds; nonexistent object fails", "--outcome", outcome,
                "--next", "Independent reproduction"]
        if evidence is not False:
            args += ["--evidence", evidence or self.capture]
        return self.call(*args, code=code)

    def supported(self):
        identifier = self.add()
        self.claim(identifier)
        self.attempt(identifier)
        return identifier

    def packet(self, identifier):
        return self.call("packet", "--id", identifier, "--owner", "controller", "--claim", "Owned boundary crossed")

    def review(self, packet, owner="reviewer", evidence=None, verdict="reproduced", code=0):
        return self.call("verify", "--packet", packet["packet"], "--owner", owner,
                         "--verdict", verdict, "--note", "Fresh fixture comparison",
                         "--control", "Baseline and negative tested", "--procedure", "New owned fixtures",
                         "--evidence", evidence or self.fresh, code=code)

    def state(self):
        return json.loads((self.run / "run.json").read_text())

    def change_state(self, state):
        (self.run / "run.json").write_text(json.dumps(state))

    def test_complete_workflow_and_resume(self):
        identifier = self.supported()
        self.assertEqual(self.call("context")["hypotheses"][0]["id"], identifier)
        packet = self.packet(identifier)
        body = json.loads(Path(packet["path"]).read_text())
        self.assertNotIn("attempts", body)
        self.assertNotIn("basis", body)
        self.review(packet)
        self.call("release", "--id", identifier, "--owner", "finder", "--note", "Stopped and restored")
        self.assertTrue(self.call("check")["complete"])
        self.call("finish", "--owner", "controller", "--status", "completed", "--note", "Verified")
        self.assertFalse(self.call("context")["may_start_work"])
        self.claim(identifier, code=2)

    def test_unresolved_and_self_verification_cannot_complete(self):
        identifier = self.supported()
        self.review(self.packet(identifier), owner="finder", code=2)
        self.call("release", "--id", identifier, "--owner", "finder", "--note", "Stopped")
        self.call("finish", "--owner", "controller", "--status", "completed", "--note", "Not verified", code=2)
        self.assertEqual(self.state()["status"], "active")
        self.call("finish", "--owner", "controller", "--status", "partial", "--note", "Needs independent proof")

    def test_claim_and_resource_conflicts(self):
        first, second = self.add(), self.add()
        self.claim(first)
        self.claim(first, owner="other", code=2)
        self.claim(second, owner="other", code=2)
        self.call("release", "--id", first, "--owner", "other", "--note", "Wrong owner", code=2)
        self.call("recover", "--id", first, "--owner", "controller", "--note", "Still running", code=2)
        state = self.state()
        state["claims"][first]["expires_at"] = "2000-01-01T00:00:00+00:00"
        self.change_state(state)
        self.claim(second, owner="other", code=2)
        self.call("recover", "--id", first, "--owner", "controller", "--note", "Confirmed old worker stopped")
        self.claim(second, owner="other")

    def test_changed_claim_invalidates_review(self):
        identifier = self.supported()
        packet = self.packet(identifier)
        self.review(packet)
        self.attempt(identifier)
        self.review(packet, code=2)
        self.call("release", "--id", identifier, "--owner", "finder", "--note", "Stopped")
        self.assertFalse(self.call("check", code=1)["complete"])

    def test_latest_independent_objection_blocks_completion(self):
        identifier = self.supported()
        packet = self.packet(identifier)
        self.review(packet)
        self.review(packet, verdict="refuted")
        self.call("release", "--id", identifier, "--owner", "finder", "--note", "Stopped")
        self.call("check", code=1)

    def test_tampered_capture_and_packet_rejected(self):
        identifier = self.supported()
        packet = self.packet(identifier)
        ref = self.state()["hypotheses"][identifier]["attempts"][0]["evidence"][0]
        (self.run / ref["path"]).write_text("modified")
        self.call("context", code=1)
        self.review(packet, code=2)

    def test_copied_evidence_not_fresh(self):
        identifier = self.supported()
        self.review(self.packet(identifier), evidence=self.capture, code=2)

    def test_attempt_requires_claim_and_evidence(self):
        identifier = self.add()
        self.attempt(identifier, code=2)
        self.claim(identifier)
        self.attempt(identifier, evidence=False, code=2)
        self.attempt(identifier, outcome="blocked", evidence=False)
        self.assertEqual(self.call("show", "--id", identifier)["disposition"], "blocked")

    def test_sensitive_evidence_and_symlink_rejected(self):
        identifier = self.add()
        self.claim(identifier)
        self.capture.write_text("Authorization: Bearer synthetic-do-not-store")
        self.attempt(identifier, code=2)
        self.assertNotIn("synthetic-do-not-store", (self.run / "run.json").read_text())
        link = self.root / "link.txt"
        link.symlink_to(self.fresh)
        self.attempt(identifier, evidence=link, code=2)

    def test_json_credentials_rejected_before_copy(self):
        identifier = self.add()
        self.claim(identifier)
        for text in ('{"password":"synthetic-secret"}', '{"access_token":"synthetic-secret"}',
                     '{"Authorization":"Bearer synthetic-secret"}',
                     r'{"pass\u0077ord":"synthetic-secret"}'):
            with self.subTest(text=text):
                self.capture.write_text(text)
                self.attempt(identifier, code=2)
                self.assertFalse((self.run / "evidence").exists())

    def test_sensitive_parent_symlink_rejected(self):
        identifier = self.add()
        self.claim(identifier)
        private = self.root / "sensitive"
        private.mkdir()
        (private / "capture.txt").write_text("Synthetic private fixture, no credential pattern")
        alias = self.root / "safe"
        alias.symlink_to(private, target_is_directory=True)
        self.attempt(identifier, evidence=alias / "capture.txt", code=2)
        self.assertFalse((self.run / "evidence").exists())

    def test_expired_budget_and_claim_allow_explicit_late_record_only(self):
        identifier = self.add()
        self.claim(identifier)
        state = self.state()
        state["deadline"] = "2000-01-01T00:00:00+00:00"
        state["claims"][identifier]["expires_at"] = state["deadline"]
        self.change_state(state)
        self.attempt(identifier, code=2)
        self.call("attempt", "--id", identifier, "--owner", "finder", "--late-record",
                  "--outcome", "blocked", "--observation", "Previous test ended without required access",
                  "--identity", "researcher A", "--procedure", "Previously obtained observation only",
                  "--control", "No new tests", "--next", "Coordinator resolves missing access")
        self.assertTrue(self.state()["hypotheses"][identifier]["attempts"][0]["late_record"])
        self.claim(identifier, code=2)

    def test_finalized_partial_run_can_link_continuation(self):
        self.add()
        self.call("finish", "--owner", "controller", "--status", "partial", "--note", "Interrupted")
        child = Path(self.call("init", "--root", self.root, "--target", "demo", "--scope-file", self.scope,
                              "--owner", "controller", "--objective", "Continue open question",
                              "--parent-run", self.run)["run"])
        output = self.invoke("context", run=child)
        self.assertEqual(json.loads(output.stdout)["data"]["parent_run"]["path"], str(self.run))

    def test_summary_pagination(self):
        first, second = self.add(), self.add()
        self.assertEqual(self.call("next", "--limit", 1)["queue"][0]["id"], first)
        self.assertEqual(self.call("next", "--limit", 1, "--offset", 1)["queue"][0]["id"], second)
        self.assertEqual(self.call("context", "--limit", 1, "--offset", 1)["hypotheses"][0]["id"], second)

    def test_lifecycle_space_reserved_when_normal_growth_fills_run(self):
        spec = importlib.util.spec_from_file_location("bug_bounty_helper", SCRIPT)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        helper.MAX_BYTES = 12000
        helper.LIFECYCLE_RESERVE = 4000
        self.call("resource", "add", "--name", "fixture", "--owner", "finder", "--note", "Stop fixture")
        state = self.state()
        state["padding"] = "x" * (7900 - len(helper.encode(state)))
        self.change_state(state)
        def execute(*args):
            return helper.execute(helper.parser().parse_args(["--run", str(self.run), *args]))
        with self.assertRaisesRegex(ValueError, "growth limit"):
            execute("add", "--owner", "finder", "--question", "q" * 200, "--basis", "Observed fixture",
                    "--prerequisites", "Owned fixture", "--test", "Compare fixtures", "--supports", "Effect",
                    "--refutes", "Control enforced")
        self.assertEqual(self.state()["hypotheses"], {})
        execute("resource", "clean", "--name", "fixture", "--owner", "finder", "--note", "Confirmed stopped",
                "--evidence", str(self.fresh))
        execute("finish", "--owner", "controller", "--status", "partial", "--note", "Clean handoff")
        self.assertEqual(self.state()["status"], "partial")

    def test_registered_cleanup_required_even_for_partial(self):
        self.call("resource", "add", "--name", "fixture-process", "--owner", "finder", "--note", "Exact fixture teardown")
        self.call("finish", "--owner", "controller", "--status", "partial", "--note", "Work incomplete", code=2)
        self.call("resource", "clean", "--name", "fixture-process", "--owner", "other",
                  "--note", "Wrong owner", "--evidence", self.fresh, code=2)
        self.call("resource", "clean", "--name", "fixture-process", "--owner", "finder",
                  "--note", "Confirmed stopped", "--evidence", self.fresh)
        self.call("finish", "--owner", "controller", "--status", "partial", "--note", "Clean handoff")

    def test_budget_expiry_stops_claims_not_handoff(self):
        identifier = self.add()
        state = self.state()
        state["deadline"] = "2000-01-01T00:00:00+00:00"
        self.change_state(state)
        self.assertFalse(self.call("next")["may_start_work"])
        self.claim(identifier, code=2)
        self.call("finish", "--owner", "controller", "--status", "partial", "--note", "Budget expired")

    def test_concurrent_claims_have_one_winner(self):
        identifier = self.add()
        def claim(owner):
            return self.invoke("claim", "--id", identifier, "--owner", owner).returncode
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ["worker-a", "worker-b"]))
        self.assertEqual(sorted(results), [0, 2])

    def test_initial_event_is_not_rewritten_by_attempt(self):
        identifier = self.supported()
        event = next(e for e in self.state()["events"] if e["kind"] == "hypothesis_added")
        self.assertEqual(event["data"]["attempts"], [])
        self.assertEqual(len(self.state()["hypotheses"][identifier]["attempts"]), 1)

    def test_managed_evidence_escape_fails_closed(self):
        identifier = self.supported()
        state = self.state()
        state["hypotheses"][identifier]["attempts"][0]["evidence"][0]["path"] = "../../outside.txt"
        self.change_state(state)
        self.call("context", code=1)

    def test_next_queues_verification_and_removes_resolved_work(self):
        identifier = self.supported()
        self.assertEqual(self.call("next")["queue"][0]["action"], "independent_reproduction")
        self.review(self.packet(identifier))
        self.assertEqual(self.call("next")["queue"][0]["action"], "final_triage")

    def test_claim_renewal_cannot_drop_mutation_resource(self):
        identifier = self.add()
        self.claim(identifier)
        self.call("claim", "--id", identifier, "--owner", "finder", code=2)
        self.assertEqual(self.state()["claims"][identifier]["resources"], ["account-A"])

    def test_packet_tampering_rejected(self):
        identifier = self.supported()
        packet = self.packet(identifier)
        Path(packet["path"]).write_text('{"claim":"changed"}')
        self.review(packet, code=2)

    def test_installer_idempotent_and_does_not_overwrite(self):
        destinations = [self.root / n for n in ("opencode", "codex", "bin")]
        args = [sys.executable, str(INSTALL), "--opencode-dir", str(destinations[0]),
                "--codex-dir", str(destinations[1]), "--bin-dir", str(destinations[2])]
        for _ in range(2):
            result = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        command = destinations[2] / "bug-bounty"
        command.unlink()
        command.write_text("unrelated existing command")
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(command.read_text(), "unrelated existing command")

    def test_rename_retires_only_owned_legacy_installation_links(self):
        directories = [self.root / n for n in ("opencode", "codex", "bin")]
        for directory in directories:
            directory.mkdir()
        source = SCRIPT.parents[2]
        for directory in directories[:2]:
            for name in ("pentest", "pentest-map"):
                (directory / name).symlink_to(source / name, target_is_directory=True)
        (directories[2] / "pentest").symlink_to(source / "pentest/scripts/pentest.py")
        unrelated = directories[1] / "pentest-report"
        unrelated.write_text("unrelated user installation")
        args = [sys.executable, str(INSTALL), "--opencode-dir", str(directories[0]),
                "--codex-dir", str(directories[1]), "--bin-dir", str(directories[2])]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for directory in directories[:2]:
            self.assertFalse((directory / "pentest").is_symlink())
            self.assertFalse((directory / "pentest-map").is_symlink())
            self.assertTrue((directory / "bug-bounty").is_symlink())
        self.assertFalse((directories[2] / "pentest").is_symlink())
        self.assertTrue((directories[2] / "bug-bounty").is_symlink())
        self.assertEqual(unrelated.read_text(), "unrelated user installation")

    def test_legacy_run_remains_readable_and_can_parent_renamed_run(self):
        self.add()
        self.call("finish", "--owner", "controller", "--status", "partial", "--note", "Continue later")
        old_directory = self.run.parent.parent / "pentest"
        old_directory.mkdir()
        old_run = old_directory / self.run.name
        self.run.rename(old_run)
        self.run = old_run
        self.assertEqual(self.call("context")["status"], "partial")
        child = Path(self.call("init", "--root", self.root, "--target", "demo", "--scope-file", self.scope,
                              "--owner", "controller", "--objective", "Continue bounty investigation",
                              "--parent-run", old_run)["run"])
        self.assertEqual(child.parent.name, "bug-bounty")
        result = self.invoke("context", run=child)
        self.assertEqual(json.loads(result.stdout)["data"]["parent_run"]["path"], str(old_run))


if __name__ == "__main__":
    unittest.main()
