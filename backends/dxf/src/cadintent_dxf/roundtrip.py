"""The honest "opens clean" round-trip check (#24 decision 5).

"Opens clean" is defined as the ezdxf headless round-trip, explicitly not
AutoCAD's opinion (ezdxf has tolerated files LT refused):

(a) the saved file is re-read **fresh** with ``ezdxf.readfile`` — never the
    in-memory doc: the build must not be its own witness;
(b) ``audit()`` on the reloaded doc must report zero errors; applied fixes
    are reported, not hidden;
(c) every ``derived`` tag and label string is re-derived against source +
    format and compared as an exact formatted string; ``literal`` text is
    reported present-but-unverifiable — visible vacuity, never a fake pass.

The external DXFIN oracle (accoreconsole) is an opt-in local hook — see
:mod:`cadintent_dxf.oracle`; CI never claims more than this library
round-trip proves.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

import ezdxf

from cadintent.presentation import ResolvedPresentation
from cadintent.snapshot import model_from_doc

from .render import build_plan


def verify_roundtrip(
    dxf_path: str,
    snapshot_doc: dict[str, Any],
    resolved: ResolvedPresentation,
    scale: Decimal,
) -> dict[str, Any]:
    """Fresh readfile + audit + exact re-derivation of every derived string.

    Returns {audit_errors, audit_fixes, derived_checked, mismatches,
    literal_unverified} — empty ``audit_errors`` and ``mismatches`` is the
    round-trip passing; ``literal_unverified`` is visible, never a pass.
    """
    model = model_from_doc(snapshot_doc)
    plan = build_plan(model, resolved, scale)

    doc = ezdxf.readfile(dxf_path)  # fresh — never the in-memory doc
    auditor = doc.audit()
    msp = doc.modelspace()

    mtext_texts = Counter(entity.dxf.text for entity in msp.query("MTEXT"))
    attribs_by_tag: dict[str, Counter] = {}
    for insert in msp.query("INSERT"):
        for attrib in insert.attribs:
            attribs_by_tag.setdefault(attrib.dxf.tag, Counter())[attrib.dxf.text] += 1

    mismatches: list[dict[str, Any]] = []
    literal_unverified: list[dict[str, Any]] = []
    derived_checked = 0

    for label in plan.labels:
        expected = label.text
        if not label.derived:
            literal_unverified.append(
                {"kind": "label", "rule": label.rule, "subject": label.ulid,
                 "text": expected, "status": "present_but_unverifiable"}
            )
            continue
        derived_checked += 1
        if mtext_texts[expected] > 0:
            mtext_texts[expected] -= 1
        else:
            mismatches.append(
                {"kind": "label", "rule": label.rule, "subject": label.ulid,
                 "expected": expected}
            )

    for insert in plan.inserts:
        for attrib in insert.attribs:
            if not attrib.derived:
                literal_unverified.append(
                    {"kind": "attrib", "tag": attrib.tag, "subject": insert.ulid,
                     "text": attrib.text, "status": "present_but_unverifiable"}
                )
                continue
            derived_checked += 1
            pool = attribs_by_tag.get(attrib.tag, Counter())
            if pool[attrib.text] > 0:
                pool[attrib.text] -= 1
            else:
                mismatches.append(
                    {"kind": "attrib", "tag": attrib.tag, "subject": insert.ulid,
                     "expected": attrib.text}
                )

    return {
        "audit_errors": [str(e) for e in auditor.errors],
        "audit_fixes": len(auditor.fixes),
        "derived_checked": derived_checked,
        "mismatches": mismatches,
        "literal_unverified": literal_unverified,
    }
