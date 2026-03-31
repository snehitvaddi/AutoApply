"""
Lever Applier — Uses OpenClaw browser CLI for form automation.

Lever key differences from Greenhouse:
  - Full name is ONE field (e.g. "Jane Doe"), not separate first/last
  - NO comboboxes — all dropdowns are radio buttons
  - Single page, straight to "Submit application"
  - No EEO section on the apply page
  - Work auth: radio buttons for Yes/No
"""

import os
import re
import json
import time
import logging
from typing import Optional

from applier.base import BaseApplier, ApplyResult
from applier.greenhouse import (
    browser, snapshot, fill_fields, click_ref, select_option,
    upload_file, take_screenshot, wait_load, navigate_url,
    parse_snapshot, match_text_field, match_dropdown, evaluate_js,
)
from config import SCREENSHOT_DIR

logger = logging.getLogger(__name__)


class LeverApplier(BaseApplier):
    """Applies to Lever jobs using OpenClaw browser CLI.

    Lever forms are simpler than Greenhouse:
    - Single name field (full name)
    - All questions on one page
    - Radio buttons instead of comboboxes
    """

    def apply(self, apply_url: str) -> ApplyResult:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

        try:
            # 1. Open the application form
            logger.info(f"Navigating to {apply_url}")
            navigate_url(apply_url)
            wait_load(5000)
            time.sleep(1)

            # 2. Snapshot
            raw = snapshot()
            if not raw:
                return ApplyResult(success=False, error="no snapshot", retriable=True)

            fields = parse_snapshot(raw)
            logger.info(f"Found {len(fields)} interactive elements")

            if len(fields) < 3:
                return ApplyResult(success=False, error="too few fields", retriable=True)

            # 3. Batch fill text fields
            # Lever uses "Full name" as one field, so answer-key has "full name" -> "First Last"
            text_fills = []
            for f in fields:
                if f["type"] == "textbox" and f["label"]:
                    val = match_text_field(f["label"], self.answer_key)
                    if val:
                        text_fills.append({"ref": f["ref"], "type": "textbox", "value": val})

            if text_fills:
                fill_fields(json.dumps(text_fills))
                logger.info(f"Filled {len(text_fills)} text fields")

            # 4. Upload resume
            for f in fields:
                ll = f["label"].lower()
                if any(kw in ll for kw in ["resume", "cv", "attach", "upload"]) and f["type"] in (
                    "button", "link", "generic",
                ):
                    logger.info(f"Uploading resume via ref {f['ref']}")
                    upload_file(self.resume_path, f["ref"])
                    time.sleep(2)
                    break

            # 5. Handle radio buttons (Lever uses radios for work auth, sponsorship, etc.)
            for f in fields:
                if f["type"] == "radio" and f["label"]:
                    answer = match_dropdown(f["label"], self.answer_key)
                    if answer and answer.lower() in f["label"].lower():
                        click_ref(f["ref"])
                        time.sleep(0.3)
                        logger.info(f"Selected radio: {f['label']}")

            # 6. Handle select dropdowns (if any)
            for f in fields:
                if f["type"] == "select" and f["label"]:
                    answer = match_dropdown(f["label"], self.answer_key)
                    if answer:
                        select_option(f["ref"], answer)
                        logger.info(f"Selected '{answer}' for '{f['label']}'")

            # 7. Handle checkboxes
            for f in fields:
                if f["type"] == "checkbox":
                    ll = f["label"].lower()
                    if any(kw in ll for kw in ["agree", "acknowledge", "consent", "terms", "privacy"]):
                        click_ref(f["ref"])
                        time.sleep(0.3)

            # 8. Find and click submit
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
            time.sleep(2)

            # Lever submit fix: the button click alone sometimes doesn't fire.
            # Use JS requestSubmit() as backup to ensure the form actually posts.
            evaluate_js("() => { const f = document.querySelector('form'); if (f) f.requestSubmit(); }")
            time.sleep(3)

            img = take_screenshot()
            return ApplyResult(success=True, screenshot=img)

        except Exception as e:
            logger.exception(f"Lever apply failed for {apply_url}")
            img = take_screenshot()
            return ApplyResult(success=False, screenshot=img, error=str(e), retriable=True)
