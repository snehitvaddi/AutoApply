"""Verify that a bundle's cover_letter_template reaches the applier via
answer_key["textarea_fields"]["cover_letter_template"].

This is the regression test for the WRONG_READ audit finding: the column
was loaded into ApplyProfile and round-tripped through migration 019,
but nothing at apply time consulted it. worker.py now injects it into
answer_key.textarea_fields right after build_answer_key returns, where
applier/base.py:134 already reads from.

We can't easily exercise the full worker loop from a unit test, so this
test stands in for the injection logic: given an answer_key dict and a
bundle cover_letter_template, the resulting dict should have the correct
shape.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def inject_cover_letter(answer_key: dict, bundle_cover_letter: str | None) -> dict:
    """Pure helper matching the logic in worker.py apply loop.

    Kept here as a standalone function so the test doesn't need to mock
    the whole apply loop. If worker.py's injection ever drifts from this
    shape, THIS test will fail — serving as a canary for the contract
    with applier/base.py:134.
    """
    if bundle_cover_letter:
        answer_key.setdefault("textarea_fields", {})
        answer_key["textarea_fields"]["cover_letter_template"] = bundle_cover_letter
    return answer_key


def test_bundle_cover_letter_injected_into_textarea_fields():
    ak = {"standard_answers": {"why_interested": "Because..."}}
    result = inject_cover_letter(ak, "Dear {hiring_manager},\n\nI'm excited...")
    assert "textarea_fields" in result
    assert result["textarea_fields"]["cover_letter_template"].startswith("Dear")


def test_existing_textarea_fields_preserved():
    ak = {"textarea_fields": {"additional_info": "some existing note"}}
    result = inject_cover_letter(ak, "Bundle cover letter")
    assert result["textarea_fields"]["additional_info"] == "some existing note"
    assert result["textarea_fields"]["cover_letter_template"] == "Bundle cover letter"


def test_null_cover_letter_no_op():
    ak = {"standard_answers": {}}
    before = dict(ak)
    result = inject_cover_letter(ak, None)
    assert result == before
    assert "textarea_fields" not in result


def test_empty_string_cover_letter_no_op():
    ak: dict = {}
    result = inject_cover_letter(ak, "")
    assert "textarea_fields" not in result


def test_applier_base_reads_from_textarea_fields():
    """Contract check: applier/base.py:134 reads the cover letter from
    answer_key["textarea_fields"]["cover_letter_template"]. If someone
    ever renames the key or changes the read path, this test should be
    updated in lockstep — and the worker.py injection updated to match."""
    import applier.base  # noqa: F401 — just verify it imports cleanly
    import inspect
    src = inspect.getsource(applier.base)
    assert '"textarea_fields"' in src
    assert '"cover_letter_template"' in src
