"""Identity resolution: request email -> user -> every identifier ever held.

Matching is exact on canonical forms (emails lower-cased, phones as digits,
SHA-256 email hashes). Fuzzy matching is deliberately avoided: the dataset is
full of look-alike decoys (``mnovak939594@`` vs ``mnovak9395@``, ``.jr``
suffixes, shared surnames) where similarity would create false links.

Names are recorded as *exposure* identifiers (a record showing the name still
exposes the person) but are never used to link a record to a subject.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional

from .models import norm_ident
from .ablation import off


def email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


@dataclass
class Subject:
    user_id: str
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    hashes: set[str] = field(default_factory=set)
    names: set[str] = field(default_factory=set)
    audit_ids: list[str] = field(default_factory=list)   # identity changes used

    @property
    def link_keys(self) -> set[str]:
        """Values that prove a record belongs to this subject."""
        return {self.user_id.lower()} | self.emails | self.phones | self.hashes

    @property
    def exposure_keys(self) -> set[str]:
        return self.link_keys | self.names


class IdentityIndex:
    def __init__(self, identities: list[dict[str, str]], audit_log: list[dict[str, str]]):
        self.current = {r["user_id"]: r for r in identities}
        self.changes: dict[str, list[dict[str, str]]] = {}
        for a in sorted(audit_log, key=lambda a: (a["event_time"], a["audit_id"])):
            self.changes.setdefault(a["user_id"], []).append(a)
        self.email_to_users: dict[str, set[str]] = {}
        for uid, r in self.current.items():
            self._index_email(r["email"], uid)
        for uid, lst in self.changes.items():
            for a in lst:
                if a["field_name"] == "email":
                    self._index_email(a["old_value"], uid)
                    self._index_email(a["new_value"], uid)

    def _index_email(self, email: str, uid: str) -> None:
        if email:
            self.email_to_users.setdefault(email.strip().lower(), set()).add(uid)

    def resolve(self, email: str) -> list[str]:
        return sorted(self.email_to_users.get(email.strip().lower(), set()))

    def subject(self, user_id: str, as_of: Optional[str] = None) -> Subject:
        """Identifier closure for ``user_id``.

        All historical values are included regardless of ``as_of``: every value
        the person ever held may still sit in an older copy. ``as_of`` only
        limits which audit rows are *cited* as evidence of a change.
        """
        r = self.current[user_id]
        s = Subject(user_id=user_id)
        s.emails.add(r["email"].strip().lower())
        if r.get("phone"):
            s.phones.add(norm_ident(r["phone"]))
        if r.get("email_hash"):
            s.hashes.add(r["email_hash"].lower())
        if r.get("name"):
            s.names.add(r["name"].strip().lower())
        for a in ([] if off("history") else self.changes.get(user_id, [])):
            if not as_of or a["event_time"] <= as_of:
                s.audit_ids.append(a["audit_id"])
            for v in (a["old_value"], a["new_value"]):
                if not v:
                    continue
                if a["field_name"] == "email":
                    s.emails.add(v.strip().lower())
                elif a["field_name"] == "phone":
                    s.phones.add(norm_ident(v))
                elif a["field_name"] == "email_hash":
                    s.hashes.add(v.strip().lower())
                elif a["field_name"] in ("name", "full_name"):
                    s.names.add(v.strip().lower())
        s.hashes |= {email_hash(e) for e in s.emails}
        return s
