"""
SmartRecruiters Applier — Uses OpenClaw browser CLI for form automation.

SmartRecruiters key differences:
  - Has "Confirm your email" field (must fill email twice)
  - City uses autocomplete combobox
  - May have multi-page flow (page 1 = personal info, page 2 = screening)
  - Resume upload is a separate section at bottom
  - "Next" button instead of "Submit" on page 1
"""

import os
import json
import time
import logging

from applier.base import BaseApplier, ApplyResult
from applier.greenhouse import (
    browser, snapshot, fill_fields, click_ref, select_option,
    upload_file, take_screenshot, wait_load, navigate_url,
    parse_snapshot, match_text_field, match_dropdown,
    type_into, press_key,
)
from config import SCREENSHOT_DIR

logger = logging.getLogger(__name__)


class SmartRecruitersApplier(BaseApplier):
    """Applies to SmartRecruiters jobs using OpenClaw browser CLI.

    SmartRecruiters forms have a unique "Confirm your email" field
    and may use a multi-page flow with a "Next" button.
    """

    def apply(self, apply_url: str) -> ApplyResult:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

        try:
            # 1. Navigate
            logger.info(f"Navigating to {apply_url}")
            navigate_url(apply_url)
            wait_load(8000)
            time.sleep(2)

            # 2. Snapshot
            raw = snapshot()
            if not raw:
                return ApplyResult(success=False, error="no snapshot", retriable=True)

            fields = parse_snapshot(raw)
            logger.info(f"Found {len(fields)} interactive elements")

            if len(fields) < 3:
                return ApplyResult(success=False, error="too few fields", retriable=True)

            # 3. Batch fill text fields (including "Confirm your email")
            email = self.answer_key.get("text_fields", {}).get("email", "")
            text_fills = []
            for f in fields:
                if f["type"] == "textbox" and f["label"]:
                    ll = f["label"].lower()
                    # SmartRecruiters has "Confirm your email" — fill with same email
                    if "confirm" in ll and "email" in ll:
                        text_fills.append({"ref": f["ref"], "type": "textbox", "value": email})
                    else:
                        val = match_text_field(f["label"], self.answer_key)
                        if val:
                            text_fills.append({"ref": f["ref"], "type": "textbox", "value": val})

            if text_fills:
                fill_fields(json.dumps(text_fills))
                logger.info(f"Filled {len(text_fills)} text fields")

            # 4. Handle city autocomplete combobox
            for f in fields:
                if f["type"] == "combo" and "city" in f["label"].lower():
                    location = self.answer_key.get("location_autocomplete", {}).get("search_term", "")
                    if location:
                        click_ref(f["ref"])
                        time.sleep(0.3)
                        type_into(f["ref"], location)
                        time.sleep(2)
                        raw2 = snapshot()
                        fields2 = parse_snapshot(raw2)
                        for f2 in fields2:
                            if location.lower() in f2["label"].lower():
                                click_ref(f2["ref"])
                                time.sleep(0.5)
                                break
                    break

            # 5. Upload resume
            for f in fields:
                ll = f["label"].lower()
                if any(kw in ll for kw in ["resume", "cv", "choose a file", "upload", "drop"]) and f["type"] in (
                    "button", "link", "generic",
                ):
                    logger.info(f"Uploading resume via ref {f['ref']}")
                    upload_file(self.resume_path, f["ref"])
                    time.sleep(3)
                    break

            # 6. Handle dropdowns
            for f in fields:
                if f["type"] in ("combo", "select") and f["label"]:
                    if "city" in f["label"].lower():
                        continue  # already handled
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

            # 7. Handle checkboxes
            for f in fields:
                if f["type"] == "checkbox":
                    ll = f["label"].lower()
                    if any(kw in ll for kw in ["agree", "acknowledge", "consent", "terms", "privacy"]):
                        click_ref(f["ref"])
                        time.sleep(0.3)

            # 8. Find and click Next/Submit
            time.sleep(0.5)
            raw_final = snapshot()
            fields_final = parse_snapshot(raw_final)

            submit_ref = None
            for f in fields_final:
                ll = f["label"].lower()
                if f["type"] in ("button", "link") and ("next" in ll or "submit" in ll or "apply" in ll):
                    submit_ref = f["ref"]
                    break

            if not submit_ref:
                return ApplyResult(success=False, error="no submit/next button", retriable=False)

            logger.info(f"Clicking {submit_ref}")
            click_ref(submit_ref)
            time.sleep(3)

            # 9. Check for page 2 (screening questions)
            raw_page2 = snapshot()
            if raw_page2 and "submit" in raw_page2.lower():
                fields_page2 = parse_snapshot(raw_page2)
                # Handle any screening dropdowns/radios on page 2
                for f in fields_page2:
                    if f["type"] in ("combo", "select", "radio") and f["label"]:
                        answer = match_dropdown(f["label"], self.answer_key)
                        if answer:
                            if f["type"] == "radio" and answer.lower() in f["label"].lower():
                                click_ref(f["ref"])
                                time.sleep(0.3)
                            elif f["type"] == "select":
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

                # Find and click final submit
                raw_final2 = snapshot()
                fields_final2 = parse_snapshot(raw_final2)
                for f in fields_final2:
                    ll = f["label"].lower()
                    if f["type"] in ("button", "link") and ("submit" in ll or "apply" in ll):
                        click_ref(f["ref"])
                        time.sleep(3)
                        break

            img = take_screenshot()
            return ApplyResult(success=True, screenshot=img)

        except Exception as e:
            logger.exception(f"SmartRecruiters apply failed for {apply_url}")
            img = take_screenshot()
            return ApplyResult(success=False, screenshot=img, error=str(e), retriable=True)
