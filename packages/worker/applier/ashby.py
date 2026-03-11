"""
Ashby Applier — Uses OpenClaw browser CLI for form automation.

Ashby key differences:
  - Location can LOOK filled but fail validation -> press Enter to commit
  - Resume upload: target input#_systemfield_resume directly
  - CRITICAL: Wait 45+ seconds after resume upload before submit (transient lock)
  - Use browser type instead of fill for text fields (React SPA)
  - May have silent anti-bot blocks
"""

import os
import json
import time
import logging

from applier.base import BaseApplier, ApplyResult
from applier.greenhouse import (
    browser, snapshot, click_ref, select_option,
    upload_file, take_screenshot, wait_load, navigate_url,
    parse_snapshot, match_text_field, match_dropdown,
    type_into, evaluate_js, press_key,
)
from config import SCREENSHOT_DIR

logger = logging.getLogger(__name__)


class AshbyApplier(BaseApplier):
    """Applies to Ashby jobs using OpenClaw browser CLI.

    Ashby forms are React SPAs with specific quirks around
    resume uploads (45s wait) and location validation (Enter to commit).
    """

    def apply(self, apply_url: str) -> ApplyResult:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

        try:
            # 1. Navigate (reuse tab)
            logger.info(f"Navigating to {apply_url}")
            navigate_url(apply_url)
            wait_load(8000)
            time.sleep(2)  # Ashby SPAs need extra load time

            # 2. Snapshot
            raw = snapshot()
            if not raw:
                return ApplyResult(success=False, error="no snapshot", retriable=True)

            fields = parse_snapshot(raw)
            logger.info(f"Found {len(fields)} interactive elements")

            if len(fields) < 3:
                return ApplyResult(success=False, error="too few fields", retriable=True)

            # 3. Fill text fields — Ashby REQUIRES `type` instead of `fill`
            #    `fill` sets DOM values without triggering React events,
            #    causing aria-invalid=true on all fields at submit time.
            for f in fields:
                if f["type"] == "textbox" and f["label"]:
                    val = match_text_field(f["label"], self.answer_key)
                    if val:
                        click_ref(f["ref"])
                        time.sleep(0.2)
                        type_into(f["ref"], val)
                        time.sleep(0.3)
                        # Press Enter for location fields to commit autocomplete
                        if "location" in f["label"].lower():
                            time.sleep(1)
                            press_key("Enter")
                            time.sleep(0.5)

            # 4. Upload resume
            resume_uploaded = False
            for f in fields:
                ll = f["label"].lower()
                if any(kw in ll for kw in ["resume", "cv", "attach", "upload"]) and f["type"] in (
                    "button", "link", "generic",
                ):
                    logger.info(f"Uploading resume via ref {f['ref']}")
                    upload_file(self.resume_path, f["ref"])
                    resume_uploaded = True
                    break

            if not resume_uploaded:
                # Try the system field directly
                evaluate_js("""() => {
                    const input = document.querySelector('input#_systemfield_resume, input[type="file"]');
                    if (input) input.click();
                }""")
                time.sleep(1)

            # CRITICAL: Wait after resume upload — Ashby has a transient lock
            if resume_uploaded:
                logger.info("Waiting 45s for Ashby resume processing...")
                time.sleep(45)

            # 5. Handle dropdowns — re-snapshot after EACH combobox because refs change
            #    Ashby DOM refs are unstable after any combobox interaction
            current_fields = fields
            for f in current_fields:
                if f["type"] in ("combo", "select") and f["label"]:
                    answer = match_dropdown(f["label"], self.answer_key)
                    if answer:
                        if f["type"] == "select":
                            select_option(f["ref"], answer)
                        else:
                            click_ref(f["ref"])
                            time.sleep(0.5)
                            raw_dd = snapshot()
                            dd_fields = parse_snapshot(raw_dd)
                            for opt in dd_fields:
                                if answer.lower() in opt["label"].lower():
                                    click_ref(opt["ref"])
                                    time.sleep(0.3)
                                    break
                        logger.info(f"Set '{answer}' for '{f['label']}'")
                        # Re-snapshot to get fresh refs (Ashby DOM changes after combobox)
                        time.sleep(0.5)
                        raw_refreshed = snapshot()
                        current_fields = parse_snapshot(raw_refreshed)

            # 6. Checkboxes — re-snapshot first since refs may have changed
            raw_cb = snapshot()
            fields_cb = parse_snapshot(raw_cb)
            for f in fields_cb:
                if f["type"] == "checkbox":
                    ll = f["label"].lower()
                    if any(kw in ll for kw in ["agree", "acknowledge", "consent", "terms", "privacy"]):
                        click_ref(f["ref"])
                        time.sleep(0.3)

            # 7. Submit
            time.sleep(0.5)
            raw_final = snapshot()
            fields_final = parse_snapshot(raw_final)

            submit_ref = None
            for f in fields_final:
                ll = f["label"].lower()
                if f["type"] in ("button", "link") and ("submit" in ll or "apply" in ll):
                    submit_ref = f["ref"]
                    break

            if not submit_ref:
                return ApplyResult(success=False, error="no submit button", retriable=False)

            logger.info(f"Submitting via ref {submit_ref}")
            click_ref(submit_ref)
            time.sleep(3)

            # Check for validation errors (Ashby shows alert with missing fields)
            raw_post = snapshot()
            post_text = raw_post.lower() if raw_post else ""

            # Resume upload recovery — if "resume" is in validation error, retry upload
            if "resume" in post_text and ("required" in post_text or "missing" in post_text):
                logger.warning("Resume validation failed — retrying upload via autofill")
                evaluate_js("""() => {
                    const input = document.querySelector('input#_systemfield_resume');
                    if (input) input.click();
                }""")
                time.sleep(2)
                upload_file(self.resume_path, submit_ref)  # re-arm upload
                time.sleep(45)
                click_ref(submit_ref)
                time.sleep(3)

            # Radio button retry — Ashby radio values may not register on first submit
            if "corrections" in post_text or "invalid" in post_text:
                logger.warning("Validation errors on first submit — retrying")
                time.sleep(1)
                click_ref(submit_ref)
                time.sleep(3)

            img = take_screenshot()
            return ApplyResult(success=True, screenshot=img)

        except Exception as e:
            logger.exception(f"Ashby apply failed for {apply_url}")
            img = take_screenshot()
            return ApplyResult(success=False, screenshot=img, error=str(e), retriable=True)
