"""
Greenhouse Applier — Multi-user version of fast-apply-greenhouse.py.

Uses OpenClaw browser CLI commands for form automation:
  - openclaw browser navigate <url>  (reuse existing tab)
  - openclaw browser open <url>      (open new tab)
  - openclaw browser snapshot --efficient --interactive
  - openclaw browser fill --fields '[{...}]'
  - openclaw browser click <ref>
  - openclaw browser select <ref> <value>
  - openclaw browser upload '<path>' (arm file chooser, then click)
  - openclaw browser screenshot --full-page --type png
  - openclaw browser evaluate --fn '<js>'
  - openclaw browser wait --load networkidle
  - openclaw browser type <ref> "<text>"
  - openclaw browser press <key>
"""

import os
import re
import json
import time
import logging
import subprocess
from typing import Optional

from applier.base import BaseApplier, ApplyResult
from config import SCREENSHOT_DIR

logger = logging.getLogger(__name__)


# ─── OpenClaw Browser CLI Helpers ────────────────────────────────────────────

def browser(cmd: str, timeout: int = 15) -> str:
    """Run an openclaw browser command, return stdout."""
    full_cmd = f"openclaw browser {cmd}"
    try:
        r = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning(f"TIMEOUT: {cmd}")
        return ""
    except Exception as e:
        logger.error(f"ERROR: {cmd} -> {e}")
        return ""


def snapshot() -> str:
    """Take efficient interactive snapshot, return raw text."""
    return browser("snapshot --efficient --interactive", timeout=10)


def fill_fields(fields_json: str) -> str:
    """Batch fill text fields. fields_json is a JSON array of {ref, type, value}."""
    escaped = fields_json.replace("'", "'\\''")
    return browser(f"fill --fields '{escaped}'", timeout=10)


def click_ref(ref: str) -> str:
    return browser(f"click {ref}", timeout=8)


def select_option(ref: str, value: str) -> str:
    escaped_value = value.replace('"', '\\"')
    return browser(f'select {ref} "{escaped_value}"', timeout=8)


def upload_file(path: str, ref: str) -> str:
    """Two-step resume upload: arm the file chooser, then click the button.

    The arm step intercepts the next file dialog. The click triggers it.
    Using upload --ref in one shot is unreliable — arm + click is the proven pattern.
    """
    browser(f"upload '{path}'", timeout=10)  # arm the file interceptor
    time.sleep(0.3)
    return click_ref(ref)  # trigger the file dialog


def take_screenshot() -> Optional[str]:
    """Take full page screenshot, return file path."""
    out = browser("screenshot --full-page --type png", timeout=10)
    m = re.search(r'(\/\S+\.png)', out)
    return m.group(1) if m else None


def wait_load(timeout_ms: int = 5000) -> None:
    browser(f"wait --load networkidle --timeout-ms {timeout_ms}", timeout=timeout_ms // 1000 + 3)


def open_url(url: str) -> str:
    """Open URL in a new tab."""
    return browser(f'open "{url}"', timeout=10)


def navigate_url(url: str) -> str:
    """Navigate to URL in the current tab (reuse tab, faster)."""
    return browser(f'navigate "{url}"', timeout=10)


def press_key(key: str) -> str:
    """Press a keyboard key (Enter, Tab, Escape, etc.)."""
    return browser(f"press {key}", timeout=3)


def evaluate_js(js_code: str) -> str:
    escaped = js_code.replace("'", "'\\''")
    return browser(f"evaluate --fn '{escaped}'", timeout=10)


def type_into(ref: str, text: str) -> str:
    escaped = text.replace('"', '\\"')
    return browser(f'type {ref} "{escaped}"', timeout=5)


# ─── Snapshot Parsing ────────────────────────────────────────────────────────

def parse_snapshot(raw: str) -> list[dict]:
    """Parse snapshot output into a list of {ref, type, label} dicts.

    Matches lines like:
      - textbox "First Name" [ref=e9]
      - combo "Country" [ref=a3]
      - button "Submit Application" [ref=f1]
    """
    fields = []
    for line in raw.split("\n"):
        line = line.strip()
        # With label
        m = re.match(
            r'-\s+(textbox|combo|button|link|checkbox|radio|select|generic)\s+"([^"]*)".*\[ref=(\w+)\]',
            line,
        )
        if m:
            fields.append({"type": m.group(1), "label": m.group(2), "ref": m.group(3)})
            continue
        # Without label
        m2 = re.match(
            r'-\s+(textbox|combo|button|link|checkbox|radio|select|generic)\s+\[ref=(\w+)\]',
            line,
        )
        if m2:
            fields.append({"type": m2.group(1), "label": "", "ref": m2.group(2)})
    return fields


# ─── Field Matching ──────────────────────────────────────────────────────────

def match_text_field(label: str, answer_key: dict) -> Optional[str]:
    """Map a field label to its answer using the answer key text_fields mapping."""
    ll = label.lower().strip()
    text_fields = answer_key.get("text_fields", {})
    # Try exact-ish matches (label contains key)
    for key, val in text_fields.items():
        if key.lower() in ll:
            return val
    return None


def match_dropdown(label: str, answer_key: dict) -> Optional[str]:
    """Map a dropdown label to its answer using the answer key dropdown_fields mapping."""
    ll = label.lower().strip()
    dropdown_fields = answer_key.get("dropdown_fields", {})
    for key, val in dropdown_fields.items():
        if key.startswith("_"):
            continue
        if key.lower() in ll:
            return str(val) if not isinstance(val, bool) else ("Yes" if val else "No")
    return None


# ─── Greenhouse Applier ─────────────────────────────────────────────────────

class GreenhouseApplier(BaseApplier):
    """Applies to Greenhouse jobs using OpenClaw browser CLI.

    This is a multi-user adaptation of fast-apply-greenhouse.py.
    Profile data comes from self.profile (loaded from DB) instead of hardcoded values.
    Answer key comes from self.answer_key (generated from profile + template).
    Resume path comes from self.resume_path (downloaded from Supabase Storage).
    """

    @staticmethod
    def to_embed_url(url: str) -> str:
        """Convert Greenhouse board URLs to embed URLs for direct form rendering.

        Embed URLs bypass iframe restrictions and render the application form directly.
        Example: boards.greenhouse.io/company/jobs/123 -> job-boards.greenhouse.io/embed/job_app?for=company&token=123
        """
        # Pattern 1: boards.greenhouse.io/{slug}/jobs/{id}
        m = re.match(r'https?://boards\.greenhouse\.io/([^/]+)/jobs/(\d+)', url)
        if m:
            return f"https://job-boards.greenhouse.io/embed/job_app?for={m.group(1)}&token={m.group(2)}"
        # Pattern 2: boards.greenhouse.io/embed/job_app?for=...&token=... (already embed)
        if "job-boards.greenhouse.io/embed" in url:
            return url
        # Pattern 3: job_boards.greenhouse.io with gh_jid param
        m2 = re.match(r'https?://job-boards\.greenhouse\.io/([^/?]+).*[?&]gh_jid=(\d+)', url)
        if m2:
            return f"https://job-boards.greenhouse.io/embed/job_app?for={m2.group(1)}&token={m2.group(2)}"
        return url

    def apply(self, apply_url: str) -> ApplyResult:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

        try:
            # 1. Convert to embed URL for direct form access
            embed_url = self.to_embed_url(apply_url)
            logger.info(f"Opening {embed_url} (original: {apply_url})")
            navigate_url(embed_url)
            wait_load(5000)
            time.sleep(1)

            # 2. Snapshot — get all interactive field refs
            raw = snapshot()
            if not raw:
                logger.error("No snapshot returned — page may not have loaded")
                return ApplyResult(success=False, error="no snapshot", retriable=True)

            fields = parse_snapshot(raw)
            logger.info(f"Found {len(fields)} interactive elements")

            if len(fields) < 3:
                logger.error("Too few fields — form may not have loaded")
                return ApplyResult(success=False, error="too few fields", retriable=True)

            # 3. Handle phone country code dropdown FIRST (must be set before phone)
            self._set_phone_country(fields)

            # 4. Batch fill ALL text fields in one shot
            text_fills = []
            for f in fields:
                if f["type"] == "textbox" and f["label"]:
                    val = match_text_field(f["label"], self.answer_key)
                    if val:
                        text_fills.append({"ref": f["ref"], "type": "textbox", "value": val})

            if text_fills:
                fills_json = json.dumps(text_fills)
                fill_fields(fills_json)
                logger.info(f"Filled {len(text_fills)} text fields")
            else:
                logger.warning("No text fields matched")

            # 5. Upload resume
            self._upload_resume(fields)

            # 6. Handle location autocomplete combobox
            self._handle_location_combobox(fields)

            # 7. Handle dropdowns/comboboxes
            self._handle_dropdowns(fields)

            # 8. Handle checkboxes (consent, privacy, terms)
            self._handle_checkboxes(fields)

            # 9. Final snapshot to find submit button
            time.sleep(0.5)
            raw_final = snapshot()
            fields_final = parse_snapshot(raw_final)

            submit_ref = None
            for f in fields_final:
                ll = f["label"].lower()
                if f["type"] == "button" and ("submit" in ll or "apply" in ll):
                    submit_ref = f["ref"]
                    break

            if not submit_ref:
                logger.error("No submit button found")
                return ApplyResult(success=False, error="no submit button", retriable=False)

            # 10. Submit
            logger.info(f"Submitting via ref {submit_ref}")
            click_ref(submit_ref)
            time.sleep(5)  # Wait for reCAPTCHA + potential email verification

            # 11. Check for email security code verification (Stripe, Datadog, etc.)
            post_submit_raw = snapshot()
            if post_submit_raw and "security code" in post_submit_raw.lower():
                logger.info("Email security code verification detected — requesting code via callback")
                handled = self._handle_email_security_code(post_submit_raw)
                if not handled:
                    img = take_screenshot()
                    return ApplyResult(
                        success=False, screenshot=img,
                        error="email security code required but not handled",
                        retriable=True,
                    )

            # 12. Verify submission confirmation (reCAPTCHA false positive check)
            post_raw = snapshot()
            post_text = (post_raw or "").lower()
            confirmation_signals = [
                "thank you for applying",
                "application submitted",
                "thanks for applying",
                "application has been submitted",
                "we have received your application",
            ]
            is_confirmed = any(sig in post_text for sig in confirmation_signals)

            # 13. Post-submit screenshot
            img = take_screenshot()
            logger.info(f"Screenshot: {img}")

            if is_confirmed:
                return ApplyResult(success=True, screenshot=img)

            # If submit button is still visible, reCAPTCHA likely blocked silently
            still_has_submit = any(
                f["type"] == "button" and ("submit" in f["label"].lower() or "apply" in f["label"].lower())
                for f in parse_snapshot(post_raw) if f.get("label")
            )
            if still_has_submit:
                logger.warning("Submit button still present — likely reCAPTCHA blocked")
                return ApplyResult(
                    success=False, screenshot=img,
                    error="recaptcha_blocked", retriable=False,
                )

            # No confirmation text but submit button gone — likely successful
            return ApplyResult(success=True, screenshot=img)

        except Exception as e:
            logger.exception(f"Greenhouse apply failed for {apply_url}")
            img = take_screenshot()
            return ApplyResult(success=False, screenshot=img, error=str(e), retriable=True)

    def _set_phone_country(self, fields: list[dict]) -> None:
        """Set phone country code to United States BEFORE the phone field is filled."""
        for f in fields:
            ll = f["label"].lower()
            if f["type"] in ("combo", "select") and any(
                kw in ll for kw in ["country", "phone country", "dial"]
            ):
                logger.info(f"Setting phone country: {f['label']}")
                # Try JS to set United States in native <select>
                evaluate_js(
                    """() => {
                    const selects = document.querySelectorAll('select');
                    for (const s of selects) {
                        const name = (s.name || s.id || '').toLowerCase();
                        const label = s.closest('.field, .form-group')?.querySelector('label')?.textContent?.toLowerCase() || '';
                        if (name.includes('country') || label.includes('country') || label.includes('phone')) {
                            for (const o of s.options) {
                                if (o.text.includes('United States') || o.text.includes('US (+1)') || o.text.includes('US (')) {
                                    s.value = o.value;
                                    s.dispatchEvent(new Event('change', {bubbles: true}));
                                    break;
                                }
                            }
                        }
                    }
                }"""
                )
                time.sleep(0.5)
                # Also try native select command
                if f["type"] == "select":
                    select_option(f["ref"], "United States")
                else:
                    # ARIA combobox — click and pick
                    click_ref(f["ref"])
                    time.sleep(0.5)
                    raw_cc = snapshot()
                    cc_fields = parse_snapshot(raw_cc)
                    for opt in cc_fields:
                        if "united states" in opt["label"].lower() or "us" in opt["label"].lower():
                            click_ref(opt["ref"])
                            time.sleep(0.3)
                            break
                logger.info("Phone country set to United States")
                break

    def _upload_resume(self, fields: list[dict]) -> None:
        """Upload resume PDF via openclaw browser upload --ref."""
        for f in fields:
            ll = f["label"].lower()
            if any(kw in ll for kw in ["resume", "cv", "attach", "upload"]) and f["type"] in (
                "button",
                "link",
                "generic",
            ):
                logger.info(f"Uploading resume via ref {f['ref']}")
                upload_file(self.resume_path, f["ref"])
                time.sleep(2)
                return
        logger.warning("No resume upload field found")

    def _handle_location_combobox(self, fields: list[dict]) -> None:
        """Handle location autocomplete combobox (type city, select from dropdown)."""
        location_config = self.answer_key.get("location_autocomplete", {})
        search_term = location_config.get("search_term", "")
        select_text = location_config.get("select_option", "").lower()

        if not search_term:
            return

        for f in fields:
            if f["type"] == "combo" and "location" in f["label"].lower():
                logger.info("Filling location autocomplete")
                click_ref(f["ref"])
                time.sleep(0.3)
                type_into(f["ref"], search_term)
                time.sleep(2)
                # Re-snapshot for autocomplete options
                raw2 = snapshot()
                fields2 = parse_snapshot(raw2)
                for f2 in fields2:
                    if select_text and all(
                        word in f2["label"].lower() for word in select_text.split(", ")
                    ):
                        click_ref(f2["ref"])
                        time.sleep(0.5)
                        break
                break

    def _handle_dropdowns(self, fields: list[dict]) -> None:
        """Handle dropdown/combobox/select fields."""
        for f in fields:
            if f["type"] in ("combo", "select") and f["label"]:
                answer = match_dropdown(f["label"], self.answer_key)
                if answer:
                    if f["type"] == "select":
                        select_option(f["ref"], answer)
                        logger.info(f"Selected '{answer}' for '{f['label']}'")
                    else:
                        # ARIA combobox — click to open, find option, click
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

    def _handle_checkboxes(self, fields: list[dict]) -> None:
        """Click consent/privacy/terms checkboxes."""
        consent_keywords = ["agree", "acknowledge", "consent", "certify", "privacy", "terms"]
        for f in fields:
            if f["type"] == "checkbox":
                ll = f["label"].lower()
                if any(kw in ll for kw in consent_keywords):
                    click_ref(f["ref"])
                    time.sleep(0.3)
                    logger.info(f"Checked: {f['label']}")

    def _handle_email_security_code(self, snapshot_raw: str) -> bool:
        """Handle Greenhouse email security code verification (8-char code).

        Some companies (Stripe, Datadog) trigger this after first submit.
        The code arrives via email from no-reply@us.greenhouse-mail.io.
        The form shows 8 separate single-character input boxes.

        This requires a gmail_reader callback to fetch the code. If the user
        has Gmail connected, we attempt to read the code; otherwise we fail.
        """
        try:
            from gmail_reader import get_latest_verification_code
        except ImportError:
            logger.warning("gmail_reader not available — cannot handle security code")
            return False

        user_email = self.profile.get("user", {}).get("email", "")
        user_id = self.profile.get("user", {}).get("id", "")
        if not user_id:
            return False

        logger.info("Waiting 15s for security code email to arrive...")
        time.sleep(15)

        code = get_latest_verification_code(
            user_id,
            sender_filter="greenhouse-mail.io",
            subject_filter="security code",
        )
        if not code or len(code) < 8:
            logger.error(f"Could not retrieve security code (got: {code})")
            return False

        code = code[:8]
        logger.info(f"Got security code: {code[:2]}****{code[-2:]}")

        # Find the 8 textbox fields for the code
        fields = parse_snapshot(snapshot_raw)
        code_fields = [f for f in fields if f["type"] == "textbox" and not f["label"]]

        if len(code_fields) >= 8:
            # Type one character per box
            for i, char in enumerate(code[:8]):
                type_into(code_fields[i]["ref"], char)
                time.sleep(0.1)
        else:
            # Fallback: try JS to fill code boxes
            evaluate_js(
                f"""() => {{
                const inputs = document.querySelectorAll('input[maxlength="1"]');
                const code = '{code}';
                for (let i = 0; i < Math.min(inputs.length, code.length); i++) {{
                    inputs[i].value = code[i];
                    inputs[i].dispatchEvent(new Event('input', {{bubbles: true}}));
                }}
            }}"""
            )

        time.sleep(1)

        # Re-snapshot and click submit again
        raw2 = snapshot()
        fields2 = parse_snapshot(raw2)
        for f in fields2:
            ll = f["label"].lower()
            if f["type"] == "button" and ("submit" in ll or "verify" in ll):
                click_ref(f["ref"])
                time.sleep(3)
                logger.info("Security code submitted")
                return True

        logger.error("Could not find submit/verify button after entering security code")
        return False
