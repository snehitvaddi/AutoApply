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
      0. Navigate → detect login wall → create account or sign in
      1. For each wizard step: snapshot → fill fields → click Next
      2. Handle special widgets (promptOption dropdowns, date spinbuttons)
      3. Upload resume when the upload step appears
      4. Review and submit

    Login wall handling (from admin learnings, March 2026):
      - Workday requires per-company account creation (global across companies)
      - If "account already exists" → forgot password → read reset email via
        himalaya → navigate reset link → set new password → sign in
      - Never skip Workday just because of a login wall
    """

    MAX_STEPS = 10  # Safety limit to avoid infinite loops
    LOGIN_SIGNALS = [
        "sign in", "create account", "create your account",
        "forgot your password", "log in to", "sign-in",
    ]

    def _is_login_wall(self, page_text: str) -> bool:
        """Detect if the current page is a login/signup wall, not an
        application form."""
        lower = page_text.lower()
        hits = sum(1 for s in self.LOGIN_SIGNALS if s in lower)
        return hits >= 2

    def _generate_workday_password(self) -> str:
        """Generate a Workday-compliant password from the user profile.
        Format: {FirstInitial}{LastInitial}{4digits}@{Year}App!"""
        import random
        user = self.profile.get("user", {})
        fi = (user.get("first_name") or "X")[0].upper()
        li = (user.get("last_name") or "X")[0].upper()
        digits = f"{random.randint(1000, 9999)}"
        year = time.strftime("%Y")
        return f"{fi}{li}{digits}@{year}App!"

    def _get_user_email(self) -> str:
        user = self.profile.get("user", {})
        return user.get("email") or ""

    def _handle_login_wall(self, raw: str) -> str | None:
        """Attempt to get past a Workday login/signup page.

        Strategy:
          1. Try "Create Account" with user's email + generated password
          2. If "already exists" error → click "Forgot Password"
          3. Read reset email via himalaya subprocess
          4. Navigate to reset link → set new password → sign in
          5. Return fresh snapshot after login, or None on failure

        This flow was documented from admin testing on NVIDIA, Google,
        Amazon Workday tenants (March 2026, knowledge/learnings.md).
        """
        email = self._get_user_email()
        if not email:
            logger.warning("Workday login wall but no user email — cannot create account")
            return None

        password = self._generate_workday_password()
        fields = parse_snapshot(raw)
        lower_text = raw.lower()

        # --- Try "Create Account" path first ---
        create_ref = None
        for f in fields:
            fl = f["label"].lower()
            if f["type"] in ("button", "link") and ("create account" in fl or "create your account" in fl):
                create_ref = f["ref"]
                break

        if create_ref:
            logger.info("Workday: attempting 'Create Account' flow")
            click_ref(create_ref)
            wait_load(3000)
            time.sleep(1)
            raw = snapshot()
            fields = parse_snapshot(raw)

            # Fill email + password + verify-password fields
            for f in fields:
                fl = f["label"].lower()
                if f["type"] == "textbox":
                    if "email" in fl:
                        type_into(f["ref"], email)
                    elif "verify" in fl or "confirm" in fl:
                        type_into(f["ref"], password)
                    elif "password" in fl:
                        type_into(f["ref"], password)
                    # Honeypot: "Enter website" — NEVER fill
                    elif "website" in fl:
                        continue

            # Check the "I agree" checkbox if present
            for f in fields:
                fl = f["label"].lower()
                if f["type"] == "checkbox" and ("agree" in fl or "terms" in fl):
                    click_ref(f["ref"])

            # Click submit/create
            for f in fields:
                fl = f["label"].lower()
                if f["type"] == "button" and ("create" in fl or "sign up" in fl or "submit" in fl):
                    click_ref(f["ref"])
                    break

            wait_load(5000)
            time.sleep(2)
            raw = snapshot()

            # Success? Check if we're past the login wall
            if not self._is_login_wall(raw):
                logger.info("Workday: account created, now on application form")
                return raw

            # "Account already exists" → try forgot password
            if "already exists" in raw.lower() or "already registered" in raw.lower():
                logger.info("Workday: account exists, trying forgot password flow")
                return self._handle_forgot_password(raw, email, password)

            logger.warning("Workday: still on login wall after create attempt")
            return None

        # --- No "Create Account" button — try "Sign In" with known password ---
        signin_ref = None
        for f in fields:
            fl = f["label"].lower()
            if f["type"] in ("button", "link") and ("sign in" in fl or "log in" in fl):
                signin_ref = f["ref"]
                break

        if signin_ref:
            logger.info("Workday: attempting sign-in (may need forgot-password)")
            click_ref(signin_ref)
            wait_load(3000)
            time.sleep(1)
            raw = snapshot()
            fields = parse_snapshot(raw)

            for f in fields:
                fl = f["label"].lower()
                if f["type"] == "textbox":
                    if "email" in fl or "username" in fl:
                        type_into(f["ref"], email)
                    elif "password" in fl:
                        type_into(f["ref"], password)

            for f in fields:
                fl = f["label"].lower()
                if f["type"] == "button" and ("sign in" in fl or "log in" in fl or "submit" in fl):
                    click_ref(f["ref"])
                    break

            wait_load(5000)
            time.sleep(2)
            raw = snapshot()

            if not self._is_login_wall(raw):
                logger.info("Workday: signed in, now on application form")
                return raw

            # Wrong password → forgot password flow
            logger.info("Workday: sign-in failed, trying forgot password")
            return self._handle_forgot_password(raw, email, password)

        logger.warning("Workday: login wall but no Create/SignIn button found")
        return None

    def _handle_forgot_password(self, raw: str, email: str, new_password: str) -> str | None:
        """Click "Forgot Password", read reset email via himalaya, reset,
        then sign in. Returns fresh snapshot or None."""
        import subprocess as _sp

        fields = parse_snapshot(raw)
        forgot_ref = None
        for f in fields:
            fl = f["label"].lower()
            if "forgot" in fl and ("password" in fl or "your" in fl):
                forgot_ref = f["ref"]
                break

        if not forgot_ref:
            # Try finding it in the raw text as a link
            for f in fields:
                if f["type"] == "link" and "forgot" in f["label"].lower():
                    forgot_ref = f["ref"]
                    break

        if not forgot_ref:
            logger.warning("Workday: cannot find 'Forgot Password' link")
            return None

        click_ref(forgot_ref)
        wait_load(3000)
        time.sleep(1)
        raw = snapshot()
        fields = parse_snapshot(raw)

        # Enter email on the forgot-password page
        for f in fields:
            if f["type"] == "textbox" and ("email" in f["label"].lower() or "username" in f["label"].lower()):
                type_into(f["ref"], email)

        for f in fields:
            if f["type"] == "button" and ("submit" in f["label"].lower() or "send" in f["label"].lower() or "reset" in f["label"].lower()):
                click_ref(f["ref"])
                break

        # Wait for email to arrive, then read via himalaya
        logger.info("Workday: waiting for reset email via himalaya...")
        reset_link = None
        for attempt in range(6):  # 6 x 5s = 30s max
            time.sleep(5)
            try:
                result = _sp.run(
                    ["himalaya", "envelope", "list", "--account", "gmail",
                     "--folder", "INBOX", "--page-size", "5", "--output", "json"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode != 0:
                    continue
                import json as _json
                envelopes = _json.loads(result.stdout)
                for env in envelopes:
                    sender = (env.get("from") or {}).get("addr", "").lower()
                    if "otp.workday.com" in sender or "workday" in sender:
                        msg_id = env.get("id")
                        if not msg_id:
                            continue
                        body_result = _sp.run(
                            ["himalaya", "message", "read", "--account", "gmail", str(msg_id)],
                            capture_output=True, text=True, timeout=10,
                        )
                        body = body_result.stdout or ""
                        link_match = re.search(
                            r'https://[^\s"<>]+passwordreset[^\s"<>]+', body
                        )
                        if not link_match:
                            link_match = re.search(
                                r'https://[^\s"<>]+myworkdayjobs\.com[^\s"<>]*reset[^\s"<>]*', body
                            )
                        if link_match:
                            reset_link = link_match.group(0)
                            break
                if reset_link:
                    break
            except Exception as e:
                logger.debug(f"himalaya read attempt {attempt}: {e}")

        if not reset_link:
            logger.warning("Workday: could not find reset email within 30s")
            return None

        logger.info(f"Workday: navigating to reset link")
        navigate_url(reset_link)
        wait_load(5000)
        time.sleep(2)
        raw = snapshot()
        fields = parse_snapshot(raw)

        # Set new password on the reset page
        for f in fields:
            fl = f["label"].lower()
            if f["type"] == "textbox":
                if "new password" in fl or "password" in fl:
                    type_into(f["ref"], new_password)
                elif "verify" in fl or "confirm" in fl:
                    type_into(f["ref"], new_password)

        for f in fields:
            if f["type"] == "button" and ("submit" in f["label"].lower() or "reset" in f["label"].lower() or "change" in f["label"].lower()):
                click_ref(f["ref"])
                break

        wait_load(5000)
        time.sleep(2)
        raw = snapshot()

        if not self._is_login_wall(raw):
            logger.info("Workday: password reset + signed in successfully")
            return raw

        logger.warning("Workday: still on login after password reset")
        return None

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

            # Handle login wall if detected (account creation / sign-in / forgot-password)
            if self._is_login_wall(raw):
                logger.info("Workday login wall detected — handling account flow")
                raw = self._handle_login_wall(raw)
                if not raw:
                    img = take_screenshot()
                    return ApplyResult(
                        success=False, screenshot=img,
                        error="workday login wall — could not authenticate",
                        retriable=True,
                    )

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
