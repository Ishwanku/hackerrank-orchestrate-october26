"""Independent regression tests on small synthetic datasets (stdlib unittest).

Each test builds a throw-away dataset/ directory with only the rows it needs,
runs the real pipeline (load_world -> Auditor -> validator) and checks the
decision. The expected result and the reason are written next to each test;
evaluation_report.md lists them. None of these cases comes from the sample set.

Run:  python3 -m unittest discover -s code/tests -v
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))

from ghostaudit.ingest.logs import parse_line  # noqa: E402
from ghostaudit.pipeline import Auditor  # noqa: E402
from ghostaudit.world import load_world  # noqa: E402

RULES = [
    ("rule_01", "USER_PROFILE", "Always", "DELETE"),
    ("rule_03", "SEARCH_INDEX_ENTRY", "Always", "DELETE"),
    ("rule_05", "SUPPORT_MESSAGE", "Shared context", "REDACT"),
    ("rule_07", "ANALYTICS_PROFILE", "Attributable", "ANONYMIZE"),
    ("rule_12", "SECURITY_AUDIT_LOG", "Within retention", "RETAIN"),
    ("rule_14", "BACKUP_ARCHIVE", "Restore can be blocked", "RETAIN"),
    ("rule_15", "ACCOUNT_TOMBSTONE", "Stable id only", "REDACT"),
]
DELETE_TEXT = "Please permanently delete the account associated with this email address."


def sha(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


class Mini:
    """Builder for a synthetic dataset directory."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "evidence/records").mkdir(parents=True)
        (self.root / "evidence/databases").mkdir(parents=True)
        self.requests, self.users, self.audit, self.activity, self.files = [], [], [], [], []

    def user(self, uid, name, email, phone="+1 555 0100"):
        self.users.append([uid, name, email, phone, sha(email), "2026-01-01T00:00:00Z"])

    def request(self, cid, email, *, text=DELETE_TEXT, status="COMPLETE",
                requested="2026-09-01T12:00:00Z", reported="2026-09-02T12:00:00Z",
                audit="2026-09-20T12:00:00Z"):
        self.requests.append([cid, email, requested, status, reported, audit, text])

    def act(self, aid, when, etype, rid, result, details="", src="deletion_worker"):
        self.activity.append([aid, when, etype, src, "x", rid, result, details or f"{etype} {rid}"])

    def export(self, fid, when, groups: dict):
        """A service_resource_export-style JSON file: groups = {service: [records]}."""
        path = f"evidence/records/{fid}.json"
        data = {"exported_at": when, "region": "global",
                "service_exports": {svc: {"items": recs} for svc, recs in groups.items()}}
        (self.root / path).write_text(json.dumps(data))
        self.files.append([fid, path, "test", when])

    def bundle(self, fid, when, snapshots: list):
        path = f"evidence/records/{fid}.json"
        (self.root / path).write_text(json.dumps({"exported_at": when, "snapshots": snapshots}))
        self.files.append([fid, path, "test", when])

    def sql(self, fid, when, body: str):
        path = f"evidence/databases/{fid}.sql"
        (self.root / path).write_text(f"-- Captured at: {when}\n{body}")
        self.files.append([fid, path, "test", when])

    def build(self) -> Path:
        def w(name, header, rows):
            with (self.root / name).open("w", newline="") as fh:
                c = csv.writer(fh)
                c.writerow(header)
                c.writerows(rows)
        req_h = ["case_id", "email", "requested_at", "reported_status", "reported_at", "audit_at",
                 "request_text"]
        w("deletion_requests.csv", req_h, self.requests)
        w("sample_deletion_requests.csv", req_h, [])
        w("user_identities.csv", ["user_id", "name", "email", "phone", "email_hash", "updated_at"],
          self.users)
        w("user_audit_log.csv", ["audit_id", "user_id", "event_time", "field_name", "old_value",
                                 "new_value"], self.audit)
        w("system_activity.csv", ["activity_id", "event_time", "event_type", "source_system",
                                  "target_system", "resource_id", "reported_result", "details"],
          self.activity)
        w("deletion_rules.csv", ["rule_id", "data_category", "condition", "required_action"], RULES)
        w("evidence_files.csv", ["file_id", "file_path", "origin", "captured_at"], self.files)
        return self.root

    def run(self):
        world = load_world(self.build())
        auditor = Auditor(world)
        out = {r.case_id: auditor.audit(r) for r in world.requests}
        self.tmp.cleanup()               # everything is in memory by now
        return out, auditor


def ops(result):
    return [(s.operation, s.resource_id, s.evidence_id) for s in result.steps]


class AttributionTests(unittest.TestCase):
    def test_tie_is_not_attributed(self):
        """Two deletion requests share reported day and status; two unowned account
        deletions match. Expected: neither request gets an account -- a status/date
        match that is not unique does not establish identity."""
        m = Mini()
        m.user("user_1", "Ann One", "ann@example.com")
        m.user("user_2", "Bob Two", "bob@example.com")
        m.request("case_1", "ann@example.com")
        m.request("case_2", "bob@example.com")
        m.act("activity_1", "2026-09-02T10:00:00Z", "DELETE_RECORD", "account_11", "SUCCESS")
        m.act("activity_2", "2026-09-02T10:05:00Z", "DELETE_RECORD", "account_22", "SUCCESS")
        res, aud = m.run()
        for cid in ("case_1", "case_2"):
            self.assertFalse(any(r.startswith("account_") for r in aud.att.resources.get(cid, ())))
        self.assertEqual(len(aud.att.unresolved), 2)

    def test_unique_workflow_match_is_inferred(self):
        """One request (NOT_STARTED -> FAILED) and one unowned FAILED primary-profile
        deletion on the reported day. A full-table replica dump without the account
        proves it absent. Expected: COMPLETE, VERIFY_RECORD_ABSENT citing the dump,
        and the trail marks the link as inferred, not evidence."""
        m = Mini()
        m.user("user_1", "Ann One", "ann@example.com")
        m.request("case_1", "ann@example.com", status="NOT_STARTED")
        m.act("activity_1", "2026-09-02T10:00:00Z", "DELETE_RECORD", "account_11", "FAILED")
        m.sql("evidence_1", "2026-09-10T00:00:00Z",
              "CREATE TABLE customer_profiles_primary (resource_id TEXT, user_id TEXT, full_name TEXT,"
              " email TEXT, phone TEXT, account_status TEXT, updated_at TEXT);"
              "INSERT INTO customer_profiles_primary VALUES('account_99','user_9','Zed','z@x.com',"
              "'+1 1','ACTIVE','2026-09-10T00:00:00Z');")
        res, aud = m.run()
        self.assertEqual(res["case_1"].status, "COMPLETE")
        self.assertIn(("VERIFY_RECORD_ABSENT", "account_11", "evidence_1"), ops(res["case_1"]))
        self.assertEqual(aud.att.via[("case_1", "account_11")], "inferred:workflow-unique")

    def test_historical_email_hash_links_record(self):
        """The request uses the person's OLD email; a search document carries only
        the sha256 hash of that old email. Expected: the document is linked through
        the audit-log history and reported as a remaining record."""
        m = Mini()
        m.user("user_1", "Ann One", "ann.new@example.com")
        m.audit.append(["audit_1", "user_1", "2025-01-01T00:00:00Z", "email",
                        "ann.old@example.com", "ann.new@example.com"])
        m.request("case_1", "ann.old@example.com")
        m.export("evidence_1", "2026-09-10T00:00:00Z", {"search_service": [
            {"resource_id": "search_5", "observed_at": "2026-09-10T00:00:00Z",
             "email_hash": sha("ann.old@example.com"), "total_hits": 1}]})
        res, _ = m.run()
        self.assertEqual(res["case_1"].status, "INCOMPLETE")
        self.assertIn(("REPORT_REMAINING_RECORD", "search_5", "evidence_1"), ops(res["case_1"]))


class SnapshotTests(unittest.TestCase):
    def test_partial_snapshot_cannot_prove_absence_for_uncovered_person(self):
        """A records-assurance bundle covers only Bob (his audit record) and lists an
        EMPTY account collection. Ann's account was present earlier. Expected: the
        bundle does not prove Ann's account absent -> still a remaining record."""
        m = Mini()
        m.user("user_1", "Ann One", "ann@example.com")
        m.user("user_2", "Bob Two", "bob@example.com")
        m.request("case_1", "ann@example.com")
        m.export("evidence_1", "2026-09-05T00:00:00Z", {"account_service": [
            {"resource_id": "account_1", "observed_at": "2026-09-05T00:00:00Z", "status_code": 200,
             "profile": {"email": "ann@example.com"}}]})
        m.bundle("evidence_2", "2026-09-15T00:00:00Z", [
            {"captured_at": "2026-09-15T00:00:00Z", "data_store": "account_service",
             "collection": "customer_profiles", "records": []},
            {"captured_at": "2026-09-15T00:00:00Z", "data_store": "security_service",
             "collection": "security_audit_events",
             "records": [{"resource_id": "audit_record_2", "subject_reference": "user_2"}]}])
        res, _ = m.run()
        self.assertIn(("REPORT_REMAINING_RECORD", "account_1", "evidence_1"), ops(res["case_1"]))

    def test_covered_person_is_proven_absent_by_bundle(self):
        """Same bundle shape, but it covers Ann. Expected: Ann's account absent (COMPLETE)."""
        m = Mini()
        m.user("user_1", "Ann One", "ann@example.com")
        m.request("case_1", "ann@example.com")
        m.export("evidence_1", "2026-09-05T00:00:00Z", {"account_service": [
            {"resource_id": "account_1", "observed_at": "2026-09-05T00:00:00Z", "status_code": 200,
             "profile": {"email": "ann@example.com"}}]})
        m.bundle("evidence_2", "2026-09-15T00:00:00Z", [
            {"captured_at": "2026-09-15T00:00:00Z", "data_store": "account_service",
             "collection": "customer_profiles", "records": []},
            {"captured_at": "2026-09-15T00:00:00Z", "data_store": "security_service",
             "collection": "security_audit_events",
             "records": [{"resource_id": "audit_record_1", "subject_reference": "user_1"}]}])
        res, _ = m.run()
        self.assertEqual(res["case_1"].status, "COMPLETE")
        self.assertIn(("VERIFY_RECORD_ABSENT", "account_1", "evidence_2"), ops(res["case_1"]))

    def test_replica_drift_keeps_record_alive(self):
        """Primary table no longer has the account but the failover replica does.
        Expected: REPORT_REMAINING_RECORD citing the replica capture."""
        m = Mini()
        m.user("user_1", "Ann One", "ann@example.com")
        m.request("case_1", "ann@example.com")
        cols = ("(resource_id TEXT, user_id TEXT, full_name TEXT, email TEXT, phone TEXT,"
                " account_status TEXT, updated_at TEXT)")
        m.sql("evidence_1", "2026-09-10T00:00:00Z",
              f"CREATE TABLE customer_profiles_primary {cols};"
              f"CREATE TABLE customer_profiles_failover_replica {cols};"
              "INSERT INTO customer_profiles_failover_replica VALUES('account_1','user_1','Ann One',"
              "'ann@example.com','+1 555 0100','ACTIVE','2026-09-09T00:00:00Z');")
        res, _ = m.run()
        self.assertIn(("REPORT_REMAINING_RECORD", "account_1", "evidence_1"), ops(res["case_1"]))


class TemporalTests(unittest.TestCase):
    def test_evidence_after_audit_at_is_ignored(self):
        """Present at 09-10; a capture dated 09-25 (after audit_at 09-20) shows it gone.
        Expected: INCOMPLETE and the later file is never cited."""
        m = Mini()
        m.user("user_1", "Ann One", "ann@example.com")
        m.request("case_1", "ann@example.com")
        m.export("evidence_1", "2026-09-10T00:00:00Z", {"search_service": [
            {"resource_id": "search_1", "observed_at": "2026-09-10T00:00:00Z",
             "email": "ann@example.com", "total_hits": 1}]})
        m.export("evidence_2", "2026-09-25T00:00:00Z", {"search_service": [
            {"resource_id": "search_1", "observed_at": "2026-09-25T00:00:00Z",
             "query": "ann@example.com", "total_hits": 0}]})
        res, _ = m.run()
        self.assertEqual(res["case_1"].status, "INCOMPLETE")
        self.assertNotIn("evidence_2", {s.evidence_id for s in res["case_1"].steps})

    def test_success_claim_contradicted_by_readback(self):
        """The workflow claims DELETE SUCCESS; a later read-back still returns the
        profile (HTTP 200). Expected: claims never override observations ->
        REPORT_REMAINING_RECORD."""
        m = Mini()
        m.user("user_1", "Ann One", "ann@example.com")
        m.request("case_1", "ann@example.com")
        m.act("activity_1", "2026-09-02T10:00:00Z", "DELETE_RECORD", "account_1", "SUCCESS")
        m.export("evidence_1", "2026-09-10T00:00:00Z", {"account_service": [
            {"resource_id": "account_1", "observed_at": "2026-09-10T00:00:00Z", "status_code": 200,
             "profile": {"email": "ann@example.com"}}]})
        res, _ = m.run()
        self.assertIn(("REPORT_REMAINING_RECORD", "account_1", "evidence_1"), ops(res["case_1"]))

    def test_malformed_log_line_is_ignored(self):
        """A line without an ISO timestamp is skipped rather than guessed."""
        self.assertIsNone(parse_line("15/09/2026 11:00 service=x resource_id=account_1"))
        self.assertIsNotNone(parse_line("2026-09-15T11:00:00Z service=x resource_id=account_1"))


class PolicyTests(unittest.TestCase):
    def _base(self, records: dict):
        m = Mini()
        m.user("user_1", "Ann One", "ann@example.com")
        m.request("case_1", "ann@example.com")
        m.export("evidence_1", "2026-09-10T00:00:00Z", records)
        return m.run()[0]["case_1"]

    def test_tombstone_with_pii_is_redacted_not_deleted(self):
        """Tombstone keeps user_1 but still shows the email. Expected: REPORT_EXPOSED_PII
        + REDACT_RECORD + VERIFY_RECORD_REDACTED; never DELETE_RECORD."""
        r = self._base({"identity_service": [{"resource_id": "tombstone_1",
                        "observed_at": "2026-09-10T00:00:00Z", "subject_reference": "user_1",
                        "email": "ann@example.com", "account_status": "DELETED"}]})
        o = [x[0] for x in ops(r)]
        self.assertEqual(o, ["REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED"])

    def test_clean_tombstone_and_retained_audit_record_complete(self):
        """Tombstone with only the stable reference + audit record in retention.
        Expected: COMPLETE with VERIFY_RECORD_PRESENT (audit) and VERIFY_RECORD_REDACTED."""
        r = self._base({
            "identity_service": [{"resource_id": "tombstone_1", "observed_at": "2026-09-10T00:00:00Z",
                                  "subject_reference": "user_1", "email": None}],
            "security_service": [{"resource_id": "audit_record_1",
                                  "observed_at": "2026-09-10T00:00:00Z",
                                  "subject_reference": "user_1", "retention_until": "2034-01-01"}]})
        self.assertEqual(r.status, "COMPLETE")
        self.assertEqual([x[0] for x in ops(r)], ["VERIFY_RECORD_PRESENT", "VERIFY_RECORD_REDACTED"])

    def test_flow_and_restore_are_stopped_before_records_change(self):
        """Enabled connector + restorable backup + remaining search entry. Expected
        remediation order: DISABLE_DATA_FLOW, BLOCK_RESTORE, then DELETE_RECORD."""
        r = self._base({
            "integration_service": [{"resource_id": "data_flow_1", "observed_at": "2026-09-10T00:00:00Z",
                                     "customer_email": "ann@example.com", "enabled": True}],
            "backup_service": [{"resource_id": "backup_1", "observed_at": "2026-09-10T00:00:00Z",
                                "customer_reference": "user_1", "restore_allowed": True}],
            "search_service": [{"resource_id": "search_1", "observed_at": "2026-09-10T00:00:00Z",
                                "email": "ann@example.com", "total_hits": 1}]})
        rem = [s.operation for s in r.steps if s.phase == "REMEDIATION"]
        self.assertEqual(rem, ["DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD"])
        self.assertEqual(r.status, "INCOMPLETE")

    def test_identifiable_analytics_is_never_complete(self):
        """Analytics row still holding the email. Expected: INCOMPLETE with
        REPORT_EXPOSED_PII + ANONYMIZE_RECORD (not DELETE)."""
        r = self._base({"analytics_platform": [{"resource_id": "analytics_1",
                        "observed_at": "2026-09-10T00:00:00Z", "email": "ann@example.com"}]})
        self.assertEqual(r.status, "INCOMPLETE")
        self.assertIn("ANONYMIZE_RECORD", [s.operation for s in r.steps])

    def test_negated_request_is_not_applicable(self):
        """'please don't delete' is not a deletion request. Expected: NOT_APPLICABLE, []."""
        m = Mini()
        m.user("user_1", "Ann One", "ann@example.com")
        m.request("case_1", "ann@example.com",
                  text="Could you send me a copy of my data? I still use it, so please don't delete anything.")
        res, _ = m.run()
        self.assertEqual((res["case_1"].status, res["case_1"].steps), ("NOT_APPLICABLE", []))


class RealEvidenceTests(unittest.TestCase):
    """Checks on the supplied evidence files (skipped when the dataset is absent)."""
    DATA = CODE.parent / "dataset"

    @unittest.skipUnless((CODE.parent / "dataset/evidence").exists(), "dataset not present")
    def test_pdf_attachment_is_linked_to_its_customer(self):
        from ghostaudit.perception.extract import local_records, pdf_text
        text = pdf_text(self.DATA / "evidence/documents/delivery_correction_attachment.pdf")
        recs = {r["resource_id"]: r for r in local_records(text, "pdf")}
        self.assertEqual(recs["support_001"]["email"], "priya.raman@gmail.com")

    @unittest.skipUnless((CODE.parent / "dataset/evidence").exists(), "dataset not present")
    def test_unknown_evidence_id_fails_validation(self):
        from ghostaudit.validate import validate_rows
        world = load_world(self.DATA)
        req = world.requests[0]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.csv"
            step = {"step_no": 1, "phase": "VERIFICATION", "system_id": "account_service",
                    "resource_id": "account_1", "operation": "VERIFY_RECORD_ABSENT",
                    "state": "ABSENT", "evidence_id": "evidence_999"}
            with p.open("w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["case_id", "deletion_status", "steps_json"])
                w.writerow([req.case_id, "COMPLETE", json.dumps([step])])
            errs = validate_rows(p, [req], world)
        self.assertTrue(any("evidence_999" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
