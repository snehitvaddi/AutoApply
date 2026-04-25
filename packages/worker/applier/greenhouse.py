"""
Greenhouse Applier — Hybrid LLM + Browser Automation (v2).

Architecture:
  1. Navigate to embed URL
  2. Snapshot accessibility tree
  3. Send snapshot + full user profile to LLM → get structured fill mapping
  4. Execute clicks_before_fill (Add another experience, etc.) → re-snapshot if needed
  5. Execute fills, dropdowns, uploads
  6. Submit → verify → smart error recovery if needed

Uses OpenClaw browser CLI commands for form automation:
  - openclaw browser navigate <url>
  - openclaw browser snapshot --efficient --interactive
  - openclaw browser fill --fields '[{...}]'
  - openclaw browser click <ref>
  - openclaw browser select <ref> <value>
  - openclaw browser upload '<path>'
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
from config import SCREENSHOT_DIR, GREENHOUSE_RECAPTCHA

logger = logging.getLogger(__name__)


# ─── OpenClaw Browser CLI Helpers ────────────────────────────────────────────
# Moved to applier/browser.py so the Agent-SDK brain and scout sources can
# depend on the browser layer without pulling in Greenhouse-specific logic.
# Re-exported here for backward compatibility — every applier + scout that
# used to do `from applier.greenhouse import browser, snapshot, ...` keeps
# working without a find-and-replace.
from applier.browser import (  # noqa: F401
    browser,
    snapshot,
    fill_fields,
    click_ref,
    select_option,
    upload_file,
    take_screenshot,
    wait_load,
    navigate_url,
    press_key,
    evaluate_js,
    type_into,
    parse_snapshot,
)


# ─── Legacy Field Matching (fallback) ───────────────────────────────────────

def match_text_field(label: str, answer_key: dict) -> Optional[str]:
    ll = label.lower().strip()
    text_fields = answer_key.get("text_fields", {})
    for key, val in text_fields.items():
        if key.lower() in ll:
            return val
    return None


def match_dropdown(label: str, answer_key: dict) -> Optional[str]:
    ll = label.lower().strip()
    dropdown_fields = answer_key.get("dropdown_fields", {})
    for key, val in dropdown_fields.items():
        if key.startswith("_"):
            continue
        if key.lower() in ll:
            return str(val) if not isinstance(val, bool) else ("Yes" if val else "No")
    return None


# ─── LLM Integration ────────────────────────────────────────────────────────

def build_fill_prompt(snap_tree: str, profile_summary: str) -> str:
    """Build the hybrid prompt for the LLM to generate a fill mapping."""
    return f"""You are filling out a job application form.

USER PROFILE:
{profile_summary}

PAGE SNAPSHOT (accessibility tree):
{snap_tree}

INSTRUCTIONS:
Analyze every field on this form. For each one, determine the correct value from the user profile.

Return a JSON object:
{{
  "fills": [{{"ref": "eXX", "value": "...", "action": "fill"}}],
  "clicks_before_fill": [{{"ref": "eXX", "reason": "Add another experience"}}],
  "dropdowns": [{{"ref": "eXX", "search_text": "...", "action": "dropdown"}}],
  "radios": [{{"ref": "eXX", "action": "click"}}],
  "checkboxes": [{{"ref": "eXX", "action": "click"}}],
  "upload_ref": "eXX",
  "submit_ref": "eXX",
  "notes": ["any concerns"]
}}

RULES:
- For repeated sections (work exp, education), map each entry to the correct position in order
- If you see "Add another" buttons, include them in clicks_before_fill
- For dropdowns/comboboxes, provide search text that will match an option
- For Yes/No buttons on authorization/sponsorship: authorized=Yes, sponsorship=Yes
- For EEO: use the values from the profile
- For "How did you hear": LinkedIn
- For phone format, use the phone from the profile
- For ambiguous free-text ("Why interested?"), use the standard_answers from profile
- If a field label is unusual, use your best judgment to match it to profile data
"""


def build_error_prompt(snap_tree: str, errors: str, previous_fills: list, profile_summary: str) -> str:
    """Build error recovery prompt."""
    return f"""The form submission returned errors.

ERRORS ON PAGE:
{errors}

WHAT WAS PREVIOUSLY FILLED:
{json.dumps(previous_fills, indent=2)}

USER PROFILE:
{profile_summary}

PAGE SNAPSHOT:
{snap_tree}

Return JSON with fixes:
{{
  "fixes": [{{"ref": "eXX", "old_value": "...", "new_value": "...", "reason": "..."}}],
  "missing_fills": [{{"ref": "eXX", "value": "...", "action": "fill|click|dropdown"}}],
  "missing_clicks": [{{"ref": "eXX", "reason": "..."}}]
}}
"""


def call_llm(prompt: str) -> Optional[dict]:
    """Call the LLM API to get a structured fill mapping.

    Uses OpenAI-compatible API. Falls back to None on error.
    The caller should fall back to pattern-matching if this returns None.
    """
    try:
        import openai
    except ImportError:
        logger.warning("openai package not installed — skipping LLM fill")
        return None

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — skipping LLM fill")
        return None

    try:
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "You are a job application form filler. Return only valid JSON, no markdown fences."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=4000,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = re.sub(r'^```\w*\n?', '', raw)
            raw = re.sub(r'\n?```$', '', raw)
        return json.loads(raw)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return None


# ─── Mapping Executor ────────────────────────────────────────────────────────

def execute_mapping(mapping: dict, resume_path: str) -> dict:
    """Execute a fill mapping from the LLM. Returns {filled, clicked, errors}.

    DROPDOWN_ORDER rule: Fill text fields and click buttons BEFORE handling
    dropdowns. Greenhouse forms can lose focus or reset values if dropdowns
    are opened before text fields are filled.
    """
    results = {"filled": 0, "clicked": 0, "errors": []}

    # Step 1: Upload resume
    upload_ref = mapping.get("upload_ref")
    if upload_ref:
        upload_file(resume_path, upload_ref)
        time.sleep(2)

    # Step 2: Fill text fields FIRST (before dropdowns — DROPDOWN_ORDER rule)
    for f in mapping.get("fills", []):
        r = fill_fields(json.dumps([{"ref": f["ref"], "type": "textbox", "value": f["value"]}]))
        if "Error" in r:
            click_ref(f["ref"])
            time.sleep(0.2)
            type_into(f["ref"], f["value"])
        results["filled"] += 1
        time.sleep(0.2)

    # Step 3: Click radios and checkboxes BEFORE dropdowns
    for r in mapping.get("radios", []):
        click_ref(r["ref"])
        results["clicked"] += 1
        time.sleep(0.2)

    for c in mapping.get("checkboxes", []):
        click_ref(c["ref"])
        results["clicked"] += 1
        time.sleep(0.2)

    # Step 4: Handle dropdowns LAST (DROPDOWN_ORDER rule)
    for d in mapping.get("dropdowns", []):
        # Toggle flyout handling: some Greenhouse dropdowns have a "Toggle flyout"
        # button that must be clicked before the dropdown options appear.
        snap_before = snapshot()
        flyout_match = re.search(
            r'button "Toggle flyout".*?\[ref=(\w+)\]', snap_before
        )
        if flyout_match:
            click_ref(flyout_match.group(1))
            time.sleep(0.5)

        click_ref(d["ref"])
        time.sleep(0.5)
        type_into(d["ref"], d["search_text"])
        time.sleep(1)
        snap = snapshot()
        option_match = re.search(
            r'option ".*?' + re.escape(d["search_text"][:10]) + r'.*?" \[ref=(\w+)\]', snap
        )
        if option_match:
            click_ref(option_match.group(1))
        else:
            first_option = re.search(r'option "(?!Select)[^"]*" \[(?:selected )?\[?ref=(\w+)\]', snap)
            if first_option:
                click_ref(first_option.group(1))
        time.sleep(0.5)

    return results


# ─── Greenhouse Applier ─────────────────────────────────────────────────────

class GreenhouseApplier(BaseApplier):
    """Applies to Greenhouse jobs using hybrid LLM + browser automation.

    Flow:
      1. Navigate to embed URL
      2. Snapshot the form
      3. Try LLM-based fill (sends full profile + snapshot → structured mapping)
      4. If LLM unavailable, fall back to pattern-matching fill
      5. Handle clicks_before_fill for multi-entry sections (work exp, education)
      6. Submit and verify, with smart error recovery via LLM
    """

    MAX_ERROR_RETRIES = 2

    @staticmethod
    def to_embed_url(url: str) -> str:
        """Convert Greenhouse board URLs to embed URLs for direct form rendering."""
        m = re.match(r'https?://boards\.greenhouse\.io/([^/]+)/jobs/(\d+)', url)
        if m:
            return f"https://job-boards.greenhouse.io/embed/job_app?for={m.group(1)}&token={m.group(2)}"
        if "job-boards.greenhouse.io/embed" in url:
            return url
        m2 = re.match(r'https?://job-boards\.greenhouse\.io/([^/?]+).*[?&]gh_jid=(\d+)', url)
        if m2:
            return f"https://job-boards.greenhouse.io/embed/job_app?for={m2.group(1)}&token={m2.group(2)}"
        return url

    def apply(self, apply_url: str) -> ApplyResult:
        # RULE: ONE job at a time. Complete or abandon this application fully
        # (fill all fields, submit, verify success) before opening the next one.
        # Never leave partial applications or open tabs.
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

        embed_url = self.to_embed_url(apply_url)
        slug_match = re.search(r'[?&]for=([^&]+)', embed_url)
        company_slug = slug_match.group(1) if slug_match else ""

        # The Claude-brain (Agent-SDK) now owns the Claude-driven apply
        # flow. This class stays for legacy fallback when the brain is
        # disabled (APPLYLOOP_BRAIN_DISABLED=1 → worker.py --mode=legacy),
        # in which case we run the regex-based path below.

        try:
            # 0. reCAPTCHA detection: warn/flag if company is in RECAPTCHA list
            # (legacy path — reached only when Claude unavailable)
            if company_slug and company_slug.lower() in [c.lower() for c in GREENHOUSE_RECAPTCHA]:
                logger.warning(
                    f"reCAPTCHA company detected: {company_slug} — "
                    "form will be filled but submit may be blocked"
                )

            # 1. Navigate to embed URL
            logger.info(f"Opening {embed_url} (original: {apply_url})")
            navigate_url(embed_url)
            wait_load(5000)
            time.sleep(1)

            # 2. Snapshot the form
            raw = snapshot()
            if not raw:
                logger.error("No snapshot returned — page may not have loaded")
                return ApplyResult(success=False, error="no snapshot", retriable=True)

            fields = parse_snapshot(raw)
            logger.info(f"Found {len(fields)} interactive elements")

            if len(fields) < 3:
                logger.error("Too few fields — form may not have loaded")
                return ApplyResult(success=False, error="too few fields", retriable=True)

            # 3. Try hybrid LLM fill
            prof_summary = self.profile_summary()
            mapping = self._get_llm_mapping(raw, prof_summary)

            if mapping:
                return self._apply_with_mapping(mapping, raw, prof_summary)
            else:
                logger.info("LLM unavailable — falling back to pattern-matching")
                return self._apply_with_patterns(fields, raw)

        except Exception as e:
            logger.exception(f"Greenhouse apply failed for {apply_url}")
            img = take_screenshot()
            return ApplyResult(success=False, screenshot=img, error=str(e), retriable=True)

    # ─── Hybrid LLM Path ────────────────────────────────────────────────────

    def _get_llm_mapping(self, snap_raw: str, prof_summary: str) -> Optional[dict]:
        """Ask the LLM to generate a fill mapping from the snapshot + profile."""
        prompt = build_fill_prompt(snap_raw, prof_summary)
        return call_llm(prompt)

    def _apply_with_mapping(self, mapping: dict, snap_raw: str, prof_summary: str) -> ApplyResult:
        """Execute the LLM-generated mapping, handling clicks_before_fill and error recovery."""

        # Handle clicks_before_fill (e.g. "Add another experience")
        clicks_before = mapping.get("clicks_before_fill", [])
        if clicks_before:
            for c in clicks_before:
                logger.info(f"Pre-fill click: {c.get('reason', c['ref'])}")
                click_ref(c["ref"])
                time.sleep(1)

            # Re-snapshot after adding sections, then re-map
            time.sleep(2)
            new_raw = snapshot()
            if new_raw:
                new_mapping = self._get_llm_mapping(new_raw, prof_summary)
                if new_mapping:
                    # Don't re-click the "add another" buttons
                    new_mapping["clicks_before_fill"] = []
                    mapping = new_mapping

        # Execute the fill
        results = execute_mapping(mapping, self.resume_path)
        logger.info(f"LLM fill: {results['filled']} filled, {results['clicked']} clicked")

        # Submit
        submit_ref = mapping.get("submit_ref")
        return self._submit_and_verify(submit_ref, mapping.get("fills", []), prof_summary)

    # ─── Pattern-Matching Fallback Path ─────────────────────────────────────

    def _apply_with_patterns(self, fields: list[dict], snap_raw: str) -> ApplyResult:
        """Original pattern-matching approach as fallback."""

        # Phone country code
        self._set_phone_country(fields)

        # Batch fill text fields
        text_fills = []
        for f in fields:
            if f["type"] == "textbox" and f["label"]:
                val = match_text_field(f["label"], self.answer_key)
                if val:
                    text_fills.append({"ref": f["ref"], "type": "textbox", "value": val})

        if text_fills:
            fill_fields(json.dumps(text_fills))
            logger.info(f"Filled {len(text_fills)} text fields")

        # Upload resume
        self._upload_resume(fields)

        # Location autocomplete
        self._handle_location_combobox(fields)

        # Dropdowns
        self._handle_dropdowns(fields)

        # Checkboxes
        self._handle_checkboxes(fields)

        # Submit
        return self._submit_and_verify(None, text_fills, self.profile_summary())

    # ─── Submit + Verify + Error Recovery ───────────────────────────────────

    def _submit_and_verify(
        self, submit_ref: Optional[str], previous_fills: list, prof_summary: str
    ) -> ApplyResult:
        """Find submit button, click it, verify, and attempt error recovery if needed."""

        # Find submit button
        time.sleep(0.5)
        raw_final = snapshot()
        fields_final = parse_snapshot(raw_final)

        if not submit_ref:
            for f in fields_final:
                ll = f["label"].lower()
                if f["type"] == "button" and ("submit" in ll or "apply" in ll):
                    submit_ref = f["ref"]
                    break

        if not submit_ref:
            logger.error("No submit button found")
            img = take_screenshot()
            return ApplyResult(success=False, screenshot=img, error="no submit button", retriable=False)

        # Click submit
        logger.info(f"Submitting via ref {submit_ref}")
        click_ref(submit_ref)
        time.sleep(5)

        # Check for email security code
        post_submit_raw = snapshot()
        if post_submit_raw and "security code" in post_submit_raw.lower():
            logger.info("Email security code verification detected")
            handled = self._handle_email_security_code(post_submit_raw)
            if not handled:
                img = take_screenshot()
                return ApplyResult(
                    success=False, screenshot=img,
                    error="email security code required but not handled",
                    retriable=True,
                )

        # Verify submission
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
        img = take_screenshot()

        if is_confirmed:
            return ApplyResult(success=True, screenshot=img)

        # Check if submit button still visible (reCAPTCHA block)
        still_has_submit = any(
            f["type"] == "button" and ("submit" in f["label"].lower() or "apply" in f["label"].lower())
            for f in parse_snapshot(post_raw) if f.get("label")
        )

        if still_has_submit:
            # Check for form errors — try LLM error recovery
            errors = evaluate_js(
                '() => JSON.stringify(Array.from(document.querySelectorAll("[class*=error]")).map(e => e.textContent.substring(0,80)))'
            )
            if errors and errors != '"[]"' and errors != '[]':
                recovery_result = self._attempt_error_recovery(
                    post_raw, errors, previous_fills, prof_summary
                )
                if recovery_result:
                    return recovery_result

            logger.warning("Submit button still present — likely reCAPTCHA blocked")
            return ApplyResult(
                success=False, screenshot=img,
                error="recaptcha_blocked", retriable=False,
            )

        # No confirmation text AND no submit button. Previously we treated
        # "button gone = success" — but Greenhouse sometimes hides the
        # submit button after a 500/validation error without showing a
        # thank-you page. Refuse to fake success: fail loud so the
        # dashboard tells the truth and the retry path kicks in.
        return ApplyResult(
            success=False, screenshot=img,
            error="no confirmation page detected after submit — likely silent failure",
            retriable=False,
        )

    def _attempt_error_recovery(
        self, snap_raw: str, errors: str, previous_fills: list, prof_summary: str
    ) -> Optional[ApplyResult]:
        """Send errors + profile to LLM for targeted fix, then re-submit."""
        for attempt in range(self.MAX_ERROR_RETRIES):
            logger.info(f"Error recovery attempt {attempt + 1}/{self.MAX_ERROR_RETRIES}")

            prompt = build_error_prompt(snap_raw, errors, previous_fills, prof_summary)
            fix_mapping = call_llm(prompt)
            if not fix_mapping:
                return None

            # Apply fixes
            for fix in fix_mapping.get("fixes", []):
                ref = fix["ref"]
                new_val = fix["new_value"]
                fill_fields(json.dumps([{"ref": ref, "type": "textbox", "value": new_val}]))
                time.sleep(0.2)

            # Apply missing fills
            for mf in fix_mapping.get("missing_fills", []):
                action = mf.get("action", "fill")
                if action == "fill":
                    fill_fields(json.dumps([{"ref": mf["ref"], "type": "textbox", "value": mf["value"]}]))
                elif action == "click":
                    click_ref(mf["ref"])
                elif action == "dropdown":
                    click_ref(mf["ref"])
                    time.sleep(0.5)
                    type_into(mf["ref"], mf["value"])
                    time.sleep(1)
                    snap = snapshot()
                    first_option = re.search(r'option "(?!Select)[^"]*" \[ref=(\w+)\]', snap)
                    if first_option:
                        click_ref(first_option.group(1))
                time.sleep(0.2)

            # Apply missing clicks
            for mc in fix_mapping.get("missing_clicks", []):
                click_ref(mc["ref"])
                time.sleep(0.3)

            # Re-submit
            time.sleep(0.5)
            raw = snapshot()
            fields = parse_snapshot(raw)
            submit_ref = None
            for f in fields:
                ll = f["label"].lower()
                if f["type"] == "button" and ("submit" in ll or "apply" in ll):
                    submit_ref = f["ref"]
                    break

            if submit_ref:
                click_ref(submit_ref)
                time.sleep(5)

                post_raw = snapshot()
                post_text = (post_raw or "").lower()
                if any(sig in post_text for sig in [
                    "thank you", "submitted", "received your application"
                ]):
                    img = take_screenshot()
                    return ApplyResult(success=True, screenshot=img)

                # Still errors — loop for another attempt
                snap_raw = post_raw
                errors = evaluate_js(
                    '() => JSON.stringify(Array.from(document.querySelectorAll("[class*=error]")).map(e => e.textContent.substring(0,80)))'
                )

        return None  # Exhausted retries

    # ─── Helper Methods (pattern-matching fallback) ─────────────────────────

    def _set_phone_country(self, fields: list[dict]) -> None:
        for f in fields:
            ll = f["label"].lower()
            if f["type"] in ("combo", "select") and any(
                kw in ll for kw in ["country", "phone country", "dial"]
            ):
                logger.info(f"Setting phone country: {f['label']}")
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
                if f["type"] == "select":
                    select_option(f["ref"], "United States")
                else:
                    click_ref(f["ref"])
                    time.sleep(0.5)
                    raw_cc = snapshot()
                    cc_fields = parse_snapshot(raw_cc)
                    for opt in cc_fields:
                        if "united states" in opt["label"].lower() or "us" in opt["label"].lower():
                            click_ref(opt["ref"])
                            time.sleep(0.3)
                            break
                break

    def _upload_resume(self, fields: list[dict]) -> None:
        for f in fields:
            ll = f["label"].lower()
            if any(kw in ll for kw in ["resume", "cv", "attach", "upload"]) and f["type"] in (
                "button", "link", "generic",
            ):
                logger.info(f"Uploading resume via ref {f['ref']}")
                upload_file(self.resume_path, f["ref"])
                time.sleep(2)
                return
        logger.warning("No resume upload field found")

    def _handle_location_combobox(self, fields: list[dict]) -> None:
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
        for f in fields:
            if f["type"] in ("combo", "select") and f["label"]:
                answer = match_dropdown(f["label"], self.answer_key)
                if answer:
                    if f["type"] == "select":
                        select_option(f["ref"], answer)
                        logger.info(f"Selected '{answer}' for '{f['label']}'")
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

    def _handle_checkboxes(self, fields: list[dict]) -> None:
        consent_keywords = ["agree", "acknowledge", "consent", "certify", "privacy", "terms"]
        for f in fields:
            if f["type"] == "checkbox":
                ll = f["label"].lower()
                if any(kw in ll for kw in consent_keywords):
                    click_ref(f["ref"])
                    time.sleep(0.3)
                    logger.info(f"Checked: {f['label']}")

    def _handle_email_security_code(self, snapshot_raw: str) -> bool:
        """Handle Greenhouse email security code verification (8-char code)."""
        import os as _os
        from himalaya_reader import ensure_configured, find_otp
        email = getattr(self, "profile_email", None) or _os.environ.get("GMAIL_EMAIL", "")
        app_pw = getattr(self, "profile_app_password", None) or _os.environ.get("GMAIL_APP_PASSWORD", "")
        if not email or not app_pw:
            logger.warning("Greenhouse security code: no Gmail credentials — skipping")
            return False
        if not ensure_configured(email, app_pw):
            logger.warning("Greenhouse security code: himalaya not available — skipping")
            return False

        logger.info("Waiting 15s for security code email to arrive...")
        time.sleep(15)

        code = find_otp(
            sender_pattern="greenhouse-mail.io",
            subject_pattern="security code",
            timeout=45,
        )
        if not code or len(code) < 8:
            logger.error(f"Could not retrieve security code (got: {code})")
            return False

        code = code[:8]
        logger.info(f"Got security code: {code[:2]}****{code[-2:]}")

        fields = parse_snapshot(snapshot_raw)
        code_fields = [f for f in fields if f["type"] == "textbox" and not f["label"]]

        if len(code_fields) >= 8:
            for i, char in enumerate(code[:8]):
                type_into(code_fields[i]["ref"], char)
                time.sleep(0.1)
        else:
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
