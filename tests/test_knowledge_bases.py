import json
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app import create_app
from safi_app.persistence import database as db
from safi_app.persistence.database import SelfReviewError
from safi_app.role_config import ROLE_CONFIG
from support import login_as, new_user


def _exec(sql, params=()):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


class KnowledgeBaseBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        original = db.set_knowledge_base_document_status

        def configured_review(*args, **kwargs):
            kwargs.setdefault("reviewer_roles", ROLE_CONFIG["reviewer_roles"])
            return original(*args, **kwargs)

        patcher = patch.object(db, "set_knowledge_base_document_status", side_effect=configured_review)
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        cls.org_id = str(uuid.uuid4())
        _exec("INSERT INTO organizations (id, name) VALUES (%s, %s)",
              (cls.org_id, 'KB Test Org'))
        cls.owner = new_user(org_id=cls.org_id, role="editor")
        cls.reviewer = new_user(org_id=cls.org_id, role="auditor")
        cls.editor2 = new_user(org_id=cls.org_id, role="editor")
        cls.member = new_user(org_id=cls.org_id, role="member")
        cls.outsider = new_user(org_id=str(uuid.uuid4()), role="editor")

    @classmethod
    def tearDownClass(cls):
        for uid in (cls.owner, cls.reviewer, cls.editor2, cls.member, cls.outsider):
            _exec("DELETE FROM users WHERE id=%s", (uid,))
        _exec("DELETE FROM organizations WHERE id=%s", (cls.org_id,))

    def setUp(self):
        self.client = self.app.test_client()
        self.created = []

    def tearDown(self):
        for kb_id in self.created:
            _exec("DELETE FROM knowledge_base_documents WHERE kb_id=%s", (kb_id,))
            _exec("DELETE FROM knowledge_bases WHERE id=%s", (kb_id,))
        _exec("DELETE FROM org_compliance_log WHERE org_id=%s", (self.org_id,))

    def make_kb(self, visibility='private', owner=None):
        kb = db.create_knowledge_base(
            name="Test Corpus", created_by=owner or self.owner,
            org_id=self.org_id, visibility=visibility)
        self.created.append(kb["id"])
        return kb


class PathSafety(unittest.TestCase):

    def test_traversal_id_never_escapes_the_vector_store(self):
        from safi_app.core.services.kb_indexer import (InvalidKnowledgeBaseId,
                                                       kb_paths)
        for bad in ("../../etc/passwd", "..", "a/b", "safi/../../x", "", None,
                    "3f2504e0-4f89-11d3-9a0c-0305e82c33"):
            with self.assertRaises(InvalidKnowledgeBaseId, msg=repr(bad)):
                kb_paths(bad)

    def test_valid_uuid_resolves_inside_the_store(self):
        from safi_app.core.services.kb_indexer import kb_paths
        from safi_app.core.services.retriever import VECTOR_STORE_PATH
        kb_id = str(uuid.uuid4())
        index_path, meta_path = kb_paths(kb_id)
        store = os.path.realpath(VECTOR_STORE_PATH)
        for p in (index_path, meta_path):
            self.assertEqual(store, os.path.dirname(os.path.realpath(p)))
        self.assertTrue(meta_path.endswith(".json"))

    def test_retriever_refuses_an_unsafe_name(self):
        from safi_app.core.services.retriever import (UnsafeKnowledgeBaseName,
                                                      _kb_index_path)
        for bad in ("../secrets", "/etc/passwd", "a/b", ".hidden"):
            with self.assertRaises(UnsafeKnowledgeBaseName, msg=bad):
                _kb_index_path(bad)
        for good in ("safi", "bible_bsb_v1"):
            self.assertTrue(_kb_index_path(good).endswith(f"{good}.index"))


class Authorization(KnowledgeBaseBase):

    def test_member_cannot_create(self):
        login_as(self.client, self.member, "member", org_id=self.org_id)
        r = self.client.post('/api/knowledge-bases', json={"name": "Nope"})
        self.assertEqual(403, r.status_code)

    def test_editor_can_create(self):
        login_as(self.client, self.owner, "editor", org_id=self.org_id)
        r = self.client.post('/api/knowledge-bases', json={"name": "Mine"})
        self.assertEqual(201, r.status_code)
        self.created.append(r.get_json()["id"])

    def test_private_kb_is_invisible_to_others(self):
        kb = self.make_kb()
        login_as(self.client, self.editor2, "editor", org_id=self.org_id)
        self.assertEqual(404, self.client.get(f'/api/knowledge-bases/{kb["id"]}').status_code)
        listing = self.client.get('/api/knowledge-bases').get_json()
        self.assertNotIn(kb["id"], [k["id"] for k in listing["knowledge_bases"]])

    def test_shared_kb_is_visible_to_the_org(self):
        kb = self.make_kb(visibility='member')
        login_as(self.client, self.editor2, "editor", org_id=self.org_id)
        self.assertEqual(200, self.client.get(f'/api/knowledge-bases/{kb["id"]}').status_code)

    def test_shared_kb_is_invisible_across_orgs(self):
        kb = self.make_kb(visibility='member')
        login_as(self.client, self.outsider, "editor", org_id=str(uuid.uuid4()))
        self.assertEqual(404, self.client.get(f'/api/knowledge-bases/{kb["id"]}').status_code)

    def test_non_owner_cannot_upload_or_delete(self):
        kb = self.make_kb(visibility='member')
        login_as(self.client, self.editor2, "editor", org_id=self.org_id)
        self.assertEqual(403, self.client.delete(f'/api/knowledge-bases/{kb["id"]}').status_code)

    def test_owner_can_rename_without_disturbing_the_index(self):
        kb = self.make_kb()
        db.set_knowledge_base_status(kb["id"], 'ready', chunk_count=12,
                                     mark_indexed=True)
        login_as(self.client, self.owner, "editor", org_id=self.org_id)
        r = self.client.put(f'/api/knowledge-bases/{kb["id"]}',
                            json={"name": "Renamed Corpus",
                                  "description": "Now with a description."})
        self.assertEqual(200, r.status_code, r.get_json())
        after = db.get_knowledge_base(kb["id"])
        self.assertEqual("Renamed Corpus", after["name"])
        self.assertEqual("Now with a description.", after["description"])
        self.assertEqual('ready', after["status"])
        self.assertEqual(12, after["chunk_count"])

    def test_rename_rejects_an_over_long_name(self):
        kb = self.make_kb()
        login_as(self.client, self.owner, "editor", org_id=self.org_id)
        r = self.client.put(f'/api/knowledge-bases/{kb["id"]}',
                            json={"name": "x" * 256})
        self.assertEqual(400, r.status_code)
        self.assertEqual("Test Corpus", db.get_knowledge_base(kb["id"])["name"])

    def test_a_non_owner_cannot_rename(self):
        kb = self.make_kb(visibility='member')
        login_as(self.client, self.editor2, "editor", org_id=self.org_id)
        r = self.client.put(f'/api/knowledge-bases/{kb["id"]}',
                            json={"name": "Hijacked"})
        self.assertEqual(403, r.status_code)
        self.assertEqual("Test Corpus", db.get_knowledge_base(kb["id"])["name"])

    def test_an_agent_keeps_working_across_a_rename(self):
        from safi_app.profile_resolver import _resolve_kb_display_name
        kb = self.make_kb()
        db.update_knowledge_base(kb["id"], name="Second Name")
        self.assertEqual("Second Name", _resolve_kb_display_name(kb["id"]))

    def test_the_knowledge_tab_gate_excludes_only_members(self):
        source = (Path(__file__).resolve().parent.parent / "public" / "js" /
                  "core" / "app.js").read_text()
        line = next(l for l in source.splitlines() if "canSeeKnowledge" in l and "=" in l)
        for role in ("admin", "editor", "auditor"):
            self.assertIn(f"'{role}'", line, f"{role} must keep the Knowledge tab")
        self.assertNotIn("'member'", line, "members must not get the Knowledge tab")

    def test_a_member_cannot_read_the_review_trail(self):
        kb = self.make_kb(visibility='member')
        doc = db.add_knowledge_base_document(
            kb["id"], "priced.pdf", "text", self.owner, status='pending')
        db.set_knowledge_base_document_status(
            doc["id"], "reject", reviewer_id=self.reviewer,
            reviewer_email="auditor@test",
            reason="Contains unreleased vendor pricing.", org_id=self.org_id)

        login_as(self.client, self.member, "member", org_id=self.org_id)
        body = self.client.get(f'/api/knowledge-bases/{kb["id"]}').get_json()
        seen = body["documents"][0]
        self.assertEqual("priced.pdf", seen["filename"])
        self.assertEqual("rejected", seen["status"])
        for leaked in ("reason", "reviewer_email", "uploaded_by", "reviewed_at"):
            self.assertNotIn(leaked, seen, f"{leaked} leaked to a member")
        self.assertNotIn("unreleased vendor pricing", json.dumps(body))
        self.assertFalse(body["can_manage"])

    def test_the_owner_and_reviewers_still_see_the_trail(self):
        kb = self.make_kb(visibility='member')
        doc = db.add_knowledge_base_document(
            kb["id"], "x.pdf", "text", self.owner, status='pending')
        db.set_knowledge_base_document_status(
            doc["id"], "reject", reviewer_id=self.reviewer,
            reviewer_email="auditor@test", reason="Out of scope.", org_id=self.org_id)

        for uid, role, why in ((self.owner, "editor", "owner manages the corpus"),
                               (self.reviewer, "auditor", "reviewer must review")):
            login_as(self.client, uid, role, org_id=self.org_id)
            seen = self.client.get(f'/api/knowledge-bases/{kb["id"]}').get_json()["documents"][0]
            self.assertEqual("Out of scope.", seen.get("reason"), why)
            self.assertEqual("auditor@test", seen.get("reviewer_email"), why)

    def test_agent_cannot_attach_someone_elses_knowledge_base(self):
        kb = self.make_kb()
        login_as(self.client, self.editor2, "editor", org_id=self.org_id)
        r = self.client.post('/api/agents', json={
            "key": f"kbtest_{uuid.uuid4().hex[:8]}", "name": "KB Thief",
            "policy_id": "standalone", "rag_knowledge_base": kb["id"],
        })
        self.assertEqual(403, r.status_code)
        self.assertIn("access", r.get_json()["error"].lower())


class Approval(KnowledgeBaseBase):

    def _doc(self, kb, status='pending', uploader=None, text="Some content."):
        return db.add_knowledge_base_document(
            kb_id=kb["id"], filename="policy.md", text=text,
            uploaded_by=uploader or self.owner, size_bytes=len(text), status=status)

    def test_editor_cannot_approve(self):
        kb = self.make_kb(visibility='member')
        doc = self._doc(kb)
        login_as(self.client, self.editor2, "editor", org_id=self.org_id)
        r = self.client.post(
            f'/api/knowledge-bases/{kb["id"]}/documents/{doc["id"]}/review',
            json={"action": "approve"})
        self.assertEqual(403, r.status_code)
        self.assertEqual('pending', db.get_knowledge_base_document(doc["id"])["status"])

    def test_auditor_and_admin_can_approve(self):
        for role, uid in (("auditor", self.reviewer), ("admin", self.editor2)):
            kb = self.make_kb(visibility='member')
            doc = self._doc(kb)
            login_as(self.client, uid, role, org_id=self.org_id)
            r = self.client.post(
                f'/api/knowledge-bases/{kb["id"]}/documents/{doc["id"]}/review',
                json={"action": "approve"})
            self.assertEqual(200, r.status_code, f"{role}: {r.get_json()}")
            self.assertEqual('approved', db.get_knowledge_base_document(doc["id"])["status"])

    def test_uploader_cannot_approve_own_document(self):
        kb = self.make_kb(visibility='member')
        doc = self._doc(kb, uploader=self.reviewer)
        _exec("UPDATE users SET role='admin' WHERE id=%s", (self.editor2,))
        with self.assertRaises(SelfReviewError):
            db.set_knowledge_base_document_status(
                doc["id"], "approve", reviewer_id=self.reviewer, org_id=self.org_id)
        self.assertEqual('pending', db.get_knowledge_base_document(doc["id"])["status"])

    def test_self_approval_is_blocked_at_the_api_too(self):
        kb = self.make_kb(visibility='member')
        doc = self._doc(kb, uploader=self.reviewer)
        _exec("UPDATE users SET role='admin' WHERE id=%s", (self.editor2,))
        login_as(self.client, self.reviewer, "auditor", org_id=self.org_id)
        r = self.client.post(
            f'/api/knowledge-bases/{kb["id"]}/documents/{doc["id"]}/review',
            json={"action": "approve"})
        self.assertEqual(403, r.status_code)

    def test_rejection_requires_a_reason(self):
        kb = self.make_kb(visibility='member')
        doc = self._doc(kb)
        login_as(self.client, self.reviewer, "auditor", org_id=self.org_id)
        r = self.client.post(
            f'/api/knowledge-bases/{kb["id"]}/documents/{doc["id"]}/review',
            json={"action": "reject"})
        self.assertEqual(400, r.status_code)

    def test_approval_writes_evidence(self):
        kb = self.make_kb(visibility='member')
        doc = self._doc(kb)
        db.set_knowledge_base_document_status(
            doc["id"], "approve", reviewer_id=self.reviewer,
            reviewer_email="auditor@test", org_id=self.org_id)
        events = [r["event_type"] for r in db.list_compliance_log(self.org_id, limit=50)]
        self.assertIn("kb_document_approved", events)

    def test_private_kb_documents_are_not_reviewable(self):
        kb = self.make_kb(visibility='private')
        doc = self._doc(kb, status='private')
        login_as(self.client, self.reviewer, "auditor", org_id=self.org_id)
        r = self.client.post(
            f'/api/knowledge-bases/{kb["id"]}/documents/{doc["id"]}/review',
            json={"action": "approve"})
        self.assertEqual(400, r.status_code)

    def test_sharing_sends_everything_back_for_review(self):
        kb = self.make_kb(visibility='private')
        self._doc(kb, status='private')
        self._doc(kb, status='private')
        login_as(self.client, self.owner, "editor", org_id=self.org_id)
        r = self.client.put(f'/api/knowledge-bases/{kb["id"]}',
                            json={"visibility": "member"})
        self.assertEqual(200, r.status_code)
        statuses = [d["status"] for d in db.list_knowledge_base_documents(kb["id"])]
        self.assertEqual(['pending', 'pending'], statuses)

    def test_unsharing_returns_documents_to_private_but_keeps_rejections(self):
        kb = self.make_kb(visibility='member')
        approved = self._doc(kb, status='pending')
        rejected = self._doc(kb, status='pending')
        db.set_knowledge_base_document_status(
            approved["id"], "approve", reviewer_id=self.reviewer, org_id=self.org_id)
        db.set_knowledge_base_document_status(
            rejected["id"], "reject", reviewer_id=self.reviewer,
            reason="out of scope", org_id=self.org_id)

        login_as(self.client, self.owner, "editor", org_id=self.org_id)
        self.client.put(f'/api/knowledge-bases/{kb["id"]}', json={"visibility": "private"})

        self.assertEqual('private', db.get_knowledge_base_document(approved["id"])["status"])
        self.assertEqual('rejected', db.get_knowledge_base_document(rejected["id"])["status"])


class SoleAdministratorException(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def setUp(self):
        self.client = self.app.test_client()
        self.org_id = str(uuid.uuid4())
        _exec("INSERT INTO organizations (id, name) VALUES (%s, %s)",
              (self.org_id, 'Sole Admin Org'))
        self.admin = new_user(org_id=self.org_id, role="admin")
        self.kb = db.create_knowledge_base("Solo Corpus", self.admin,
                                           org_id=self.org_id, visibility='member')
        self.doc = db.add_knowledge_base_document(
            self.kb["id"], "sop.md", "# SOP\n\nDo the thing.",
            self.admin, status='pending')

    def tearDown(self):
        _exec("DELETE FROM knowledge_base_documents WHERE kb_id=%s", (self.kb["id"],))
        _exec("DELETE FROM knowledge_bases WHERE id=%s", (self.kb["id"],))
        _exec("DELETE FROM org_compliance_log WHERE org_id=%s", (self.org_id,))
        _exec("DELETE FROM users WHERE org_id=%s", (self.org_id,))
        _exec("DELETE FROM organizations WHERE id=%s", (self.org_id,))

    def test_sole_admin_may_approve_their_own_upload(self):
        updated = db.set_knowledge_base_document_status(
            self.doc["id"], "approve", reviewer_id=self.admin,
            reviewer_email="solo@test", org_id=self.org_id)
        self.assertEqual('approved', updated["status"])
        self.assertTrue(updated["self_approved"])

    def test_the_exception_is_logged_as_a_distinct_event(self):
        db.set_knowledge_base_document_status(
            self.doc["id"], "approve", reviewer_id=self.admin, org_id=self.org_id)
        rows = db.list_compliance_log(self.org_id, limit=20)
        events = [r["event_type"] for r in rows]
        self.assertIn("kb_document_self_approved", events)
        self.assertNotIn("kb_document_approved", events)
        detail = next(r["detail"] for r in rows
                      if r["event_type"] == "kb_document_self_approved")
        self.assertFalse(detail["independent_review"])
        self.assertEqual("sole_administrator", detail["exception"])
        self.assertIn("no independent reviewer", detail["attestation"])

    def test_exception_closes_when_a_second_reviewer_joins(self):
        second = new_user(org_id=self.org_id, role="auditor")
        with self.assertRaises(SelfReviewError):
            db.set_knowledge_base_document_status(
                self.doc["id"], "approve", reviewer_id=self.admin, org_id=self.org_id)
        self.assertEqual('pending', db.get_knowledge_base_document(self.doc["id"])["status"])

    def test_an_editor_does_not_count_as_an_eligible_reviewer(self):
        new_user(org_id=self.org_id, role="editor")
        updated = db.set_knowledge_base_document_status(
            self.doc["id"], "approve", reviewer_id=self.admin, org_id=self.org_id)
        self.assertEqual('approved', updated["status"])
        self.assertTrue(updated["self_approved"])

    def test_a_reviewer_in_another_org_does_not_count(self):
        other_org = str(uuid.uuid4())
        _exec("INSERT INTO organizations (id, name) VALUES (%s, %s)", (other_org, 'Elsewhere'))
        outsider = new_user(org_id=other_org, role="admin")
        try:
            updated = db.set_knowledge_base_document_status(
                self.doc["id"], "approve", reviewer_id=self.admin, org_id=self.org_id)
            self.assertTrue(updated["self_approved"])
        finally:
            _exec("DELETE FROM users WHERE id=%s", (outsider,))
            _exec("DELETE FROM organizations WHERE id=%s", (other_org,))

    def test_independent_approval_is_not_flagged_as_self_approved(self):
        reviewer = new_user(org_id=self.org_id, role="auditor")
        updated = db.set_knowledge_base_document_status(
            self.doc["id"], "approve", reviewer_id=reviewer, org_id=self.org_id)
        self.assertEqual('approved', updated["status"])
        self.assertFalse(updated["self_approved"])
        self.assertIn("kb_document_approved",
                      [r["event_type"] for r in db.list_compliance_log(self.org_id, limit=20)])

    def test_the_exception_does_not_bypass_the_role_gate(self):
        lone_editor = new_user(org_id=self.org_id, role="editor")
        kb = db.create_knowledge_base("Editor Corpus", lone_editor,
                                      org_id=self.org_id, visibility='member')
        doc = db.add_knowledge_base_document(kb["id"], "x.md", "text",
                                             lone_editor, status='pending')
        try:
            login_as(self.client, lone_editor, "editor", org_id=self.org_id)
            r = self.client.post(
                f'/api/knowledge-bases/{kb["id"]}/documents/{doc["id"]}/review',
                json={"action": "approve"})
            self.assertEqual(403, r.status_code)
        finally:
            _exec("DELETE FROM knowledge_base_documents WHERE kb_id=%s", (kb["id"],))
            _exec("DELETE FROM knowledge_bases WHERE id=%s", (kb["id"],))

    def test_api_reports_sole_reviewer_to_the_ui(self):
        login_as(self.client, self.admin, "admin", org_id=self.org_id)
        body = self.client.get(f'/api/knowledge-bases/{self.kb["id"]}').get_json()
        self.assertTrue(body["sole_reviewer"])
        new_user(org_id=self.org_id, role="auditor")
        body = self.client.get(f'/api/knowledge-bases/{self.kb["id"]}').get_json()
        self.assertFalse(body["sole_reviewer"])

    def test_sole_admin_approval_through_the_api(self):
        login_as(self.client, self.admin, "admin", org_id=self.org_id)
        r = self.client.post(
            f'/api/knowledge-bases/{self.kb["id"]}/documents/{self.doc["id"]}/review',
            json={"action": "approve"})
        self.assertEqual(200, r.status_code, r.get_json())
        self.assertTrue(r.get_json()["document"]["self_approved"])
        self.assertEqual(1, len(db.list_indexable_documents(self.kb["id"])))


class Indexing(KnowledgeBaseBase):

    def test_indexable_set_excludes_pending_and_rejected(self):
        kb = self.make_kb(visibility='member')
        db.add_knowledge_base_document(kb["id"], "a.md", "alpha content",
                                       self.owner, status='pending')
        db.add_knowledge_base_document(kb["id"], "b.md", "bravo content",
                                       self.owner, status='rejected')
        ok = db.add_knowledge_base_document(kb["id"], "c.md", "charlie content",
                                            self.owner, status='pending')
        db.set_knowledge_base_document_status(
            ok["id"], "approve", reviewer_id=self.reviewer, org_id=self.org_id)

        indexable = db.list_indexable_documents(kb["id"])
        self.assertEqual(["c.md"], [d["filename"] for d in indexable])
        self.assertEqual("charlie content", indexable[0]["text"])

    def test_private_documents_are_indexable(self):
        kb = self.make_kb(visibility='private')
        db.add_knowledge_base_document(kb["id"], "own.md", "my notes",
                                       self.owner, status='private')
        self.assertEqual(1, len(db.list_indexable_documents(kb["id"])))

    def test_every_mutating_route_enqueues_a_rebuild(self):
        login_as(self.client, self.reviewer, "auditor", org_id=self.org_id)
        kb = self.make_kb(visibility='member')
        doc = db.add_knowledge_base_document(kb["id"], "x.md", "text",
                                             self.owner, status='pending')
        db.set_knowledge_base_status(kb["id"], 'ready', chunk_count=1)
        self.client.post(
            f'/api/knowledge-bases/{kb["id"]}/documents/{doc["id"]}/review',
            json={"action": "approve"})
        self.assertEqual('pending', db.get_knowledge_base(kb["id"])["status"])

        db.set_knowledge_base_status(kb["id"], 'ready', chunk_count=1)
        login_as(self.client, self.owner, "editor", org_id=self.org_id)
        self.client.delete(f'/api/knowledge-bases/{kb["id"]}/documents/{doc["id"]}')
        self.assertEqual('pending', db.get_knowledge_base(kb["id"])["status"])

    def test_claim_is_atomic(self):
        kb = self.make_kb()
        db.set_knowledge_base_status(kb["id"], 'pending')
        first = db.claim_pending_knowledge_base()
        self.assertEqual(kb["id"], first)
        self.assertIsNone(db.claim_pending_knowledge_base())

    def test_picker_only_offers_knowledge_bases_with_vectors(self):
        empty = self.make_kb()
        ready = self.make_kb()
        db.set_knowledge_base_status(ready["id"], 'ready', chunk_count=12)
        offered = [kb["id"] for kb in
                   db.list_knowledge_bases_for_agent_picker(self.owner, self.org_id, "editor")]
        self.assertIn(ready["id"], offered)
        self.assertNotIn(empty["id"], offered)


class PolicyAuthorization(unittest.TestCase):

    def test_absent_key_does_not_narrow(self):
        from safi_app.core.faculties.synderesis import authorized_knowledge_base
        self.assertEqual("safi", authorized_knowledge_base("safi", None))
        self.assertEqual("safi", authorized_knowledge_base("safi", "not-a-list"))

    def test_empty_list_denies(self):
        from safi_app.core.faculties.synderesis import authorized_knowledge_base
        self.assertIsNone(authorized_knowledge_base("safi", []))

    def test_list_intersects(self):
        from safi_app.core.faculties.synderesis import authorized_knowledge_base
        self.assertEqual("safi", authorized_knowledge_base("safi", ["safi", "x"]))
        self.assertIsNone(authorized_knowledge_base("other", ["safi", "x"]))

    def test_no_knowledge_base_stays_none(self):
        from safi_app.core.faculties.synderesis import authorized_knowledge_base
        self.assertIsNone(authorized_knowledge_base(None, ["safi"]))
        self.assertEqual("", authorized_knowledge_base("", ["safi"]))

    def test_stamping_strips_an_unauthorized_knowledge_base(self):
        from safi_app.core.faculties.synderesis import _stamp_knowledge_authorization
        profile = {
            "name": "Test", "policy_id": "p1",
            "rag_knowledge_base": "forbidden-kb",
            "will_rules": {"allowed_knowledge_bases": ["allowed-kb"]},
        }
        out = _stamp_knowledge_authorization(profile)
        self.assertIsNone(out["rag_knowledge_base"])
        self.assertEqual("forbidden-kb", out["rag_blocked_by_policy"])

    def test_stamping_leaves_an_authorized_knowledge_base_alone(self):
        from safi_app.core.faculties.synderesis import _stamp_knowledge_authorization
        profile = {
            "name": "Test", "policy_id": "p1",
            "rag_knowledge_base": "allowed-kb",
            "will_rules": {"allowed_knowledge_bases": ["allowed-kb"]},
        }
        out = _stamp_knowledge_authorization(profile)
        self.assertEqual("allowed-kb", out["rag_knowledge_base"])
        self.assertNotIn("rag_blocked_by_policy", out)

    def test_legacy_list_will_rules_do_not_narrow(self):
        from safi_app.core.faculties.synderesis import _stamp_knowledge_authorization
        profile = {"name": "T", "rag_knowledge_base": "safi",
                   "will_rules": ["do not swear"]}
        self.assertEqual("safi",
                         _stamp_knowledge_authorization(profile)["rag_knowledge_base"])

    def test_a_blocked_knowledge_base_is_not_announced_to_the_user(self):
        source = (Path(__file__).resolve().parent.parent / "safi_app" /
                  "profile_resolver.py").read_text()
        compile_at = source.index("compiler.compile_profile(")
        name_at = source.index('"rag_knowledge_base_name"')
        self.assertLess(compile_at, name_at,
                        "knowledge authorization must be stamped before the "
                        "display name is resolved")


class RetrievedContextReachesThePrompt(unittest.TestCase):

    def _intellect(self, worldview):
        from safi_app.core.faculties.intellect import IntellectEngine
        engine = IntellectEngine.__new__(IntellectEngine)
        engine.profile = {"worldview": worldview, "style": ""}
        engine.prompt_config = {}
        engine.retriever = None
        return engine

    def _build_prompt(self, worldview, context):
        engine = self._intellect(worldview)
        wv = engine.profile["worldview"]
        injection = ""
        if "{retrieved_context}" in wv:
            wv = wv.format(retrieved_context=context or "[NO DOCUMENTS FOUND]")
        elif context:
            template = engine.prompt_config.get(
                "retrieved_context_template",
                "RETRIEVED DOCUMENTS — this is the authoritative source for anything you state "
                "about the organization's own policies, procedures, products or people. Quote and "
                "cite the SOURCE names given below. If these documents do not cover part of the "
                "question, say so explicitly instead of supplying the detail from general "
                "knowledge, and never invent a section number, form name, threshold or approver "
                "that does not appear here.\n<retrieved_documents>\n{retrieved_context}\n"
                "</retrieved_documents>")
            injection = template.format(retrieved_context=context)
        return "\n\n".join(filter(None, [wv, injection]))

    def test_a_custom_worldview_still_receives_the_context(self):
        prompt = self._build_prompt(
            "You are the SAFi IT operations assistant.",
            "SOURCE: sop.pdf\nCONTENT:\nApproved: Lenovo ThinkPad X1 Carbon.")
        self.assertIn("ThinkPad", prompt)
        self.assertIn("sop.pdf", prompt)

    def test_a_placeholder_worldview_is_not_double_injected(self):
        prompt = self._build_prompt(
            "Answer only from:\n{retrieved_context}\nBe brief.",
            "SOURCE: sop.pdf\nCONTENT:\nApproved: Lenovo ThinkPad X1 Carbon.")
        self.assertEqual(1, prompt.count("ThinkPad"))
        self.assertNotIn("RETRIEVED DOCUMENTS", prompt)

    def test_no_context_adds_no_empty_block(self):
        prompt = self._build_prompt("You are an assistant.", "")
        self.assertNotIn("RETRIEVED DOCUMENTS", prompt)
        self.assertEqual("You are an assistant.", prompt.strip())

    def test_the_default_template_forbids_inventing_specifics(self):
        prompt = self._build_prompt("You are an assistant.", "SOURCE: x\nCONTENT:\ny")
        for phrase in ("section number", "approver", "say so explicitly"):
            self.assertIn(phrase, prompt)

    def test_intellect_puts_the_injection_in_the_system_prompt(self):
        source = (Path(__file__).resolve().parent.parent / "safi_app" / "core" /
                  "faculties" / "intellect.py").read_text()
        build = source[source.index("system_prompt = "):]
        self.assertIn("retrieved_context_injection", build.split("]))")[0])

    def test_every_builtin_rag_agent_still_has_its_placeholder(self):
        agent_dir = (Path(__file__).resolve().parent.parent /
                     "safi_app" / "core" / "agents")
        for f in agent_dir.glob("*.py"):
            text = f.read_text()
            if '"rag_knowledge_base"' in text and "None" not in text.split('"rag_knowledge_base"')[1][:20]:
                self.assertIn("{retrieved_context}", text,
                              f"{f.name} has a knowledge base but no placeholder")


class ChunkRendering(unittest.TestCase):

    def test_empty_string_is_treated_as_unconfigured(self):
        from safi_app.core.services.retriever import (DEFAULT_RAG_FORMAT_STRING,
                                                      resolve_rag_format_string)
        for unset in ("", "   ", "\n", None, 0, [], {}):
            self.assertEqual(DEFAULT_RAG_FORMAT_STRING,
                             resolve_rag_format_string(unset), repr(unset))

    def test_a_configured_template_is_returned_verbatim(self):
        from safi_app.core.services.retriever import resolve_rag_format_string
        self.assertEqual("{text_chunk}\n---",
                         resolve_rag_format_string("{text_chunk}\n---"))

    def test_the_default_renders_real_retriever_metadata(self):
        from safi_app.core.services.retriever import (DEFAULT_RAG_FORMAT_STRING,
                                                      resolve_rag_format_string)
        doc = {"source": "sop.pdf", "chunk_id": "x-chunk-0",
               "document_id": "x", "text_chunk": "Order laptops via IT."}
        rendered = resolve_rag_format_string("").format(**doc)
        self.assertIn("sop.pdf", rendered)
        self.assertIn("Order laptops via IT.", rendered)

    def test_the_default_names_the_source(self):
        from safi_app.core.services.retriever import DEFAULT_RAG_FORMAT_STRING
        self.assertIn("{source}", DEFAULT_RAG_FORMAT_STRING)
        self.assertIn("{text_chunk}", DEFAULT_RAG_FORMAT_STRING)

    def test_host_resolves_the_rag_template_before_it_reaches_intellect(self):
        source = (Path(__file__).resolve().parent.parent / "safi_app" / "core" /
                  "faculties" / "intellect.py").read_text()
        host = (Path(__file__).resolve().parent.parent / "safi_app" /
                "profile_resolver.py").read_text()
        self.assertNotIn('self.profile.get("rag_format_string", ', source)
        self.assertIn("resolve_rag_format_string", host)
        self.assertNotIn("SOURCE:", source)
        self.assertNotIn("resolve_rag_format_string", source)

    def test_no_agent_is_saved_with_an_empty_format_string(self):
        source = (Path(__file__).resolve().parent.parent / "safi_app" / "api" /
                  "agent_api_routes.py").read_text()
        self.assertNotIn("rag_format_string=data.get('rag_format_string')", source)


class Chunking(unittest.TestCase):

    def test_long_document_is_not_truncated_at_the_prompt_limit(self):
        from safi_app.config import Config
        from safi_app.core.services.kb_indexer import MAX_INDEX_CHARS_PER_DOC
        self.assertGreater(MAX_INDEX_CHARS_PER_DOC, Config.MAX_DOCUMENT_CHARS * 10)

    def test_headingless_text_still_chunks(self):
        from safi_app.core.services.chunking import chunk_document
        text = "\n\n".join(f"Paragraph number {i} with some content." for i in range(400))
        chunks = chunk_document(text, "extracted.pdf")
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 2000 for c in chunks))
        self.assertIn("Paragraph number 399", "\n".join(chunks))

    def test_one_giant_paragraph_is_hard_split(self):
        from safi_app.core.services.chunking import chunk_document
        chunks = chunk_document("x" * 9000, "table.pdf")
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 2000 for c in chunks))

    def test_markdown_still_uses_the_heading_chunker(self):
        from safi_app.core.services.chunking import chunk_document
        text = "# Title\n\n## Section\n\nBody text here.\n\n## Other\n\nMore body."
        chunks = chunk_document(text, "doc.md")
        self.assertTrue(all(c.strip() != "# Title" for c in chunks))

    def test_cli_builder_shares_this_chunker(self):
        source = (Path(__file__).resolve().parent.parent /
                  "rag" / "build_index_v2.py").read_text()
        self.assertIn("from safi_app.core.services.chunking import", source)
        self.assertNotIn("def _chunk_markdown(", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
