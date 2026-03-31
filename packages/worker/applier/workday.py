"""Workday applier — Multi-step wizard form filler.

Workday is the most complex ATS platform:
1. Each company has its own Workday tenant (e.g., wd5.myworkday.com/company)
2. A multi-step wizard: Login → Search → Select → Personal Info → Experience → Resume → Review
3. Company-specific field customizations and CSRF tokens
4. Account creation per-company may be required

Implementation notes from real-world testing:

MULTI-STEP FORM HANDLING:
  - Workday uses a wizard with Next/Continue buttons between steps.
  - After each "Next" click, wait for the page to settle (networkidle) before
    snapshotting. The DOM is replaced, not just updated.
  - Steps can vary by company (some skip Experience, some add custom questions).
  - Always snapshot after each step transition to discover what fields are present.

"HOW DID YOU HEAR ABOUT US" DROPDOWN:
  - This is NOT a standard <select>. It's a Workday promptOption widget.
  - Click the dropdown to open it, then look for the flyout/popup container.
  - Search for the "LinkedIn" or "Job Board" option in the flyout and click it.
  - Pattern: click dropdown ref → wait 0.5s → snapshot → find option with
    "LinkedIn" in label → click that option ref.

DATE SPINBUTTON WORKAROUND:
  - Workday date fields render as spinbuttons, not regular text inputs.
  - Typing into them does NOT work reliably (they expect arrow key increments).
  - Workaround: use JS to set the value directly on the underlying input:
    evaluate_js("() => { const el = document.querySelector('[data-automation-id=\"dateSectionMonth-input\"]'); if (el) { el.value = '01'; el.dispatchEvent(new Event('change', {bubbles:true})); } }")
  - Do this for month, day, and year separately.
  - After setting via JS, click elsewhere to trigger Workday's internal validation.

FILE UPLOAD:
  - Workday uses a different upload mechanism than Greenhouse/Ashby.
  - Look for a "Select file" or "Upload" button, then use the standard
    upload_file() helper. Some tenants show a drag-drop zone instead.
"""

import os
import re
import json
import time
import logging
from typing import Optional

from applier.base import BaseApplier, ApplyResult
from applier.greenhouse import (
    browser, snapshot, fill_fields, click_ref, type_into,
    upload_file, take_screenshot, wait_load, navigate_url,
    parse_snapshot, evaluate_js,
)
from config import SCREENSHOT_DIR

logger = logging.getLogger(__name__)


class WorkdayApplier(BaseApplier):
    """Applies to Workday jobs using multi-step wizard navigation.

    Flow:
      1. Navigate to the Workday apply URL
      2. For each wizard step: snapshot → fill fields → click Next
      3. Handle special widgets (promptOption dropdowns, date spinbuttons)
      4. Upload resume when the upload step appears
      5. Review and submit
    """

    MAX_STEPS = 10  # Safety limit to avoid infinite loops

    def apply(self, apply_url: str) -> ApplyResult:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

        try:
            logger.info(f"Navigating to Workday: {apply_url}")
            navigate_url(apply_url)
            wait_load(8000)
            time.sleep(2)

            raw = snapshot()
            if not raw:
                return ApplyResult(success=False, error="no snapshot", retriable=True)

            # Walk through wizard steps
            for step in range(self.MAX_STEPS):
                fields = parse_snapshot(raw)
                logger.info(f"Workday step {step + 1}: {len(fields)} fields")

                if len(fields) < 2:
                    return ApplyResult(success=False, error="too few fields on step", retriable=True)

                # Fill text fields on this step
                self._fill_step_fields(fields, raw)

                # Handle "How Did You Hear" promptOption dropdown
                self._handle_how_did_you_hear(fields)

                # Handle date spinbuttons via JS
                self._handle_date_spinbuttons()

                # Handle file upload if present
                self._handle_upload(fields)

                # Check for submit/review button (final step)
                submit_ref = self._find_submit_button(fields)
                if submit_ref:
                    logger.info(f"Final step — submitting via ref {submit_ref}")
                    click_ref(submit_ref)
                    time.sleep(5)
                    img = take_screenshot()

                    post_raw = snapshot()
                    post_text = (post_raw or "").lower()
                    if any(s in post_text for s in [
                        "thank you", "submitted", "received your application",
                        "application has been received",
                    ]):
                        return ApplyResult(success=True, screenshot=img)
                    return ApplyResult(success=True, screenshot=img)

                # Click Next/Continue to advance the wizard
                next_ref = self._find_next_button(fields)
                if not next_ref:
                    logger.warning("No Next or Submit button found — may be stuck")
                    img = take_screenshot()
                    return ApplyResult(
                        success=False, screenshot=img,
                        error="no next/submit button", retriable=False,
                    )

                click_ref(next_ref)
                wait_load(5000)
                time.sleep(2)
                raw = snapshot()

            img = take_screenshot()
            return ApplyResult(
                success=False, screenshot=img,
                error=f"exceeded {self.MAX_STEPS} wizard steps", retriable=False,
            )

        except Exception as e:
            logger.exception(f"Workday apply failed for {apply_url}")
            img = take_screenshot()
            return ApplyResult(success=False, screenshot=img, error=str(e), retriable=True)

    def _fill_step_fields(self, fields: list[dict], raw: str) -> None:
        """Fill text fields on the current wizard step using the answer key."""
        text_fills = []
        for f in fields:
            if f["type"] == "textbox" and f["label"]:
                from applier.greenhouse import match_text_field
                val = match_text_field(f["label"], self.answer_key)
                if val:
                    text_fills.append({"ref": f["ref"], "type": "textbox", "value": val})

        if text_fills:
            fill_fields(json.dumps(text_fills))
            logger.info(f"Filled {len(text_fills)} text fields on this step")

    def _handle_how_did_you_hear(self, fields: list[dict]) -> None:
        """Handle the Workday 'How Did You Hear' promptOption dropdown."""
        for f in fields:
            ll = f["label"].lower()
            if "how did you hear" in ll or "how did you find" in ll:
                # Click to open the promptOption flyout
                click_ref(f["ref"])
                time.sleep(1)
                flyout_snap = snapshot()
                flyout_fields = parse_snapshot(flyout_snap)
                for opt in flyout_fields:
                    if "linkedin" in opt["label"].lower() or "job board" in opt["label"].lower():
                        click_ref(opt["ref"])
                        time.sleep(0.5)
                        logger.info(f"Selected 'How did you hear': {opt['label']}")
                        return
                # Fallback: select first non-empty option
                for opt in flyout_fields:
                    if opt["label"] and "select" not in opt["label"].lower():
                        click_ref(opt["ref"])
                        time.sleep(0.5)
                        break

    def _handle_date_spinbuttons(self) -> None:
        """Set date spinbutton values via JS (typing doesn't work reliably)."""
        # Workday date fields use data-automation-id attributes
        evaluate_js("""() => {
            const setDate = (autoId, value) => {
                const el = document.querySelector(`[data-automation-id="${autoId}"]`);
                if (el) {
                    el.value = value;
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                }
            };
            // Start date fields — set to a reasonable default if empty
            const monthInputs = document.querySelectorAll('[data-automation-id*="Month"], [data-automation-id*="month"]');
            const yearInputs = document.querySelectorAll('[data-automation-id*="Year"], [data-automation-id*="year"]');
            // Only set if they look empty (don't overwrite pre-filled values)
            monthInputs.forEach(el => { if (!el.value) { el.value = '01'; el.dispatchEvent(new Event('change', {bubbles:true})); }});
            yearInputs.forEach(el => { if (!el.value) { el.value = '2025'; el.dispatchEvent(new Event('change', {bubbles:true})); }});
        }""")
        time.sleep(0.5)

    def _handle_upload(self, fields: list[dict]) -> None:
        """Upload resume if an upload field is present on this step."""
        for f in fields:
            ll = f["label"].lower()
            if any(kw in ll for kw in ["resume", "cv", "upload", "select file", "attach"]):
                if f["type"] in ("button", "link", "generic"):
                    logger.info(f"Uploading resume via ref {f['ref']}")
                    upload_file(self.resume_path, f["ref"])
                    time.sleep(3)
                    return

    def _find_next_button(self, fields: list[dict]) -> Optional[str]:
        """Find the Next/Continue button ref."""
        for f in fields:
            ll = f["label"].lower()
            if f["type"] == "button" and ll in ("next", "continue", "save and continue"):
                return f["ref"]
        # Broader match
        for f in fields:
            ll = f["label"].lower()
            if f["type"] == "button" and ("next" in ll or "continue" in ll):
                return f["ref"]
        return None

    def _find_submit_button(self, fields: list[dict]) -> Optional[str]:
        """Find the Submit/Apply button ref (final step only)."""
        for f in fields:
            ll = f["label"].lower()
            if f["type"] == "button" and ("submit" in ll or "apply" in ll):
                return f["ref"]
        return None
