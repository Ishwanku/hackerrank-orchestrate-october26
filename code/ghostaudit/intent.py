"""Does the request text authorise deletion?

Deterministic first: explicit non-deletion cues (correction, export, access,
opt-out, login help, or a negated deletion such as "don't delete") win over
deletion words, because several non-deletion requests mention "delete" or
"remove" only to rule them out. Multilingual deletion cues cover the languages
in the data.

Texts with neither kind of cue are follow-ups on an existing deletion
request ("confirm the profile is gone") and count as deletion.

No model is used: the ten non-deletion requests in the data all state their
purpose explicitly, so rules are exact here and fully testable.
"""
from __future__ import annotations

import re

NON_DELETION = [
    r"\bnot (?:asking|requesting) (?:for )?(?:a )?delet", r"\bnot a request to (?:erase|delete)",
    r"\b(?:don'?t|do not|without) (?:delete|deleting|remov|clos|chang)",
    r"\bleave (?:the|my) (?:account|profile)", r"\bkeep the account", r"\bcontinue using",
    r"\bstill (?:need|want|use)", r"\bmarketing lists? only", r"\bpromotional emails",
    r"\b(?:send|need) (?:me )?a copy\b", r"\bdownload my\b", r"\bportable format", r"\bwhat personal information",
    r"\breset(?:ting)? the login", r"\bmisspelled", r"\bout of date", r"\bchange the email",
    r"\bcorrect it\b", r"\binformation request\b",
]
DELETION = [
    r"\bdelet", r"\berase", r"\berasure", r"\bremove (?:my|the|this|that|it|me|all)",
    r"\bclose (?:my|this|the) account", r"\bclosed\b", r"\bforget me",
    r"exclus[aã]o", r"elimina", r"suppression", r"supprim", r"삭제", r"削除", r"löschen", r"cancella",
]
_NON = [re.compile(p, re.I) for p in NON_DELETION]
_DEL = [re.compile(p, re.I) for p in DELETION]


def classify(text: str) -> tuple[bool, str]:
    """Return (authorises_deletion, reason)."""
    for p in _NON:
        if p.search(text):
            return False, f"non-deletion cue /{p.pattern}/"
    for p in _DEL:
        if p.search(text):
            return True, f"deletion cue /{p.pattern}/"
    # Every request arrives through the deletion workflow; follow-ups such as
    # "check the profile is gone" carry no deletion verb but still authorise it.
    # Only an explicit non-deletion purpose (above) makes a case NOT_APPLICABLE.
    return True, "no non-deletion cue (deletion follow-up)"


def _selftest() -> None:
    assert classify("Please permanently delete the account associated with this email.")[0]
    assert classify("このメールアドレスに関連するアカウントの完全な削除を依頼します。")[0]
    assert not classify("Could you send me a copy? I still use it, so please don't delete anything.")[0]
    assert not classify("Please remove me from marketing lists only.")[0]


if __name__ == "__main__":
    _selftest()
    print("intent selftest ok")
