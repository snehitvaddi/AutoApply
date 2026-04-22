"""LLM-driven form fill. Claude decides every value; Python just drives.

The coded appliers used to match fields via regex against a static answer_key
(match_text_field, match_dropdown). That produced generic answers, missed
novel questions, and wrote "I'm passionate about impact" for every "Why
interested?" prompt. This module replaces the matching step with a single
Claude call that returns a structured fill plan for the whole form.

Uses the `claude --print` CLI the user already has (same auth as the Chat
tab's qa_agent). No OpenAI key needed. Falls back to None if claude binary
missing or call fails, letting the caller use its legacy regex path as
fallback — so zero behavior change if the LLM path is unavailable.

Design notes:
- One call per form (snapshot + profile + answer_key in, plan out).
- Strict JSON response. Tolerant parser strips markdown fences / leading text.
- Uses a tight timeout (45s) so a stuck claude process doesn't hang the loop.
- WORKER_NO_LLM_FILL=1 disables the path entirely (ops kill switch).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from typing import Any, Callable

logger = logging.getLogger(__name__)


def claude_available() -> bool:
    """True if the `claude` CLI is on PATH and LLM-fill isn't disabled."""
    if os.environ.get("WORKER_NO_LLM_FILL", "").lower() in ("1", "true", "yes"):
        return False
    return shutil.which("claude") is not None


def call_claude(prompt: str, timeout_s: int = 45) -> str | None:
    """Run `claude --print` with the prompt, return stdout or None.

    --output-format text keeps it one-shot (no streaming). The 45s cap
    balances quality vs. per-job latency — longer and the apply loop
    starves, shorter and Claude can't finish complex forms.
    """
    try:
        r = subprocess.run(
            ["claude", "--print", "--output-format", "text", prompt],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if r.returncode != 0:
            logger.debug(f"claude exit={r.returncode}: {r.stderr[:200]}")
            return None
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning(f"claude --print timed out after {timeout_s}s")
        return None
    except Exception as e:
        logger.debug(f"claude call failed: {e}")
        return None


def parse_json_reply(text: str) -> dict | None:
    """Extract the first JSON object from Claude's reply.

    Claude sometimes wraps JSON in ```json fences or adds preamble. Be
    lenient: find the outermost {...} block and try to parse. Returns None
    if nothing usable is found.
    """
    if not text:
        return None
    # Try direct parse first
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    # Fenced ```json ... ``` block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Greedy outermost braces
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def build_fill_prompt(
    *,
    company: str,
    role: str,
    profile_summary: str,
    answer_key: dict,
    snapshot_text: str,
    jd_hint: str = "",
) -> str:
    """Construct the prompt. Claude first classifies the page, THEN plans
    the fill (or returns an action code if the page isn't a normal form).
    This lets the driver handle captchas / login walls / bot-detection /
    rate-limit pages gracefully instead of blindly clicking."""
    ak_json = json.dumps(answer_key, indent=2)[:3500]
    jd_block = f"\nJOB DESCRIPTION (for tone / company-specific answers):\n{jd_hint[:2000]}\n" if jd_hint else ""

    return f"""You are both the eyes and the hands for a job-application bot.
First CLASSIFY what kind of page this is, then either plan the fill or
emit an action code the driver should take.

Reply with STRICT JSON ONLY — no prose, no markdown fences, no explanation.

COMPANY: {company}
ROLE: {role}

USER PROFILE:
{profile_summary}

ANSWER KEY (pre-approved canonical answers the user has already vetted):
{ak_json}
{jd_block}
PAGE SNAPSHOT (accessibility tree; every interactive element has [ref=eXX]):
{snapshot_text[:9000]}

Return this exact JSON shape:
{{
  "page_state": "normal" | "captcha" | "login_wall" | "bot_detected" | "rate_limited" | "error_page" | "already_submitted" | "needs_direct_url",
  "action":     "fill_and_submit" | "skip_non_retriable" | "wait_retry" | "attempt_account_creation" | "search_direct_url",
  "reason":     "one-line human-readable reason for the action",
  "fills":      [{{"ref": "eXX", "value": "..."}}],
  "selects":    [{{"ref": "eXX", "value": "..."}}],
  "dropdowns":  [{{"ref": "eXX", "search": "..."}}],
  "radios":     [{{"ref": "eXX"}}],
  "checkboxes": [{{"ref": "eXX"}}],
  "upload_ref": "eXX" | null,
  "submit_ref": "eXX" | null,
  "custom_js":  ["() => {{ /* your arbitrary browser-side JS */ }}"]
}}

CUSTOM_JS ESCAPE HATCH — when the standard plan isn't enough:
The driver will run each string in `custom_js` via OpenClaw's `browser
evaluate --fn '<code>'` after text fills but before submit. Use this when
you need to:
  - Set values on inputs that don't respond to normal typing (React
    controlled components, masked phone fields, date pickers)
  - Dispatch synthetic events so frameworks re-render validation state
  - Click inside shadow DOM that OpenClaw's ref system can't reach
  - Pre-validate or uncheck an accidentally-checked agreement box
  - Scroll an element into view before clicking
Each item must be a SELF-CONTAINED arrow function: `() => {{ ... }}`.
No network calls. No eval of user input. Keep each under 500 chars.
Run errors are swallowed (logged at debug) so a bad script doesn't
abort the fill.

Example:
  "custom_js": [
    "() => {{ const el = document.querySelector('[data-qa=\\"phone\\"]'); if (el) {{ el.value = '+15551234567'; el.dispatchEvent(new Event('input', {{bubbles:true}})); }} }}"
  ]

PAGE-STATE CLASSIFICATION (examine the snapshot):
- "captcha": reCAPTCHA widget visible, "I'm not a robot" checkbox, Cloudflare
  challenge, hCaptcha. Action: skip_non_retriable (bots can't solve these).
- "login_wall": the page asks for username/password or "create an account"
  BEFORE showing the apply form (Workday/iCIMS). Action: attempt_account_creation
  ONLY if the form has a clear "Create account" path AND user profile has
  email; otherwise skip_non_retriable.
- "bot_detected": "unusual activity" / "confirm you're human" / "access
  denied" messages. Action: wait_retry (Python will back off).
- "rate_limited": "too many requests" / "please slow down" / 429 visible.
  Action: wait_retry.
- "error_page": 404 / "job no longer available" / "posting closed".
  Action: skip_non_retriable.
- "already_submitted": you see "Application received" / "Thank you for
  applying" BEFORE any submit click. Action: skip_non_retriable (dedup
  caught us; don't double-submit).
- "needs_direct_url": page is a LinkedIn sign-in modal or a sign-in
  gate that blocks the real apply URL. Action: search_direct_url
  (driver will try Google for the real careers page).
- "normal": page is an actual application form with fillable fields.
  Action: fill_and_submit. Follow the fill rules below.

FILL RULES (only when page_state="normal"):
- Fill EVERY required field. No blanks. If unsure, pick the most plausible
  value from the profile.
- For free-text questions (Why interested? / Tell us about a project /
  cover letter / what makes you stand out), write 2-4 sentences that are
  SPECIFIC to {company} and {role}. Reference their product, mission, or
  the JD if present. Do NOT write generic "I'm passionate about making
  impact" style answers.
- Text fields BEFORE dropdowns (dropdowns can shift refs).
- For Greenhouse specifically: set country dropdown to "United States"
  BEFORE the phone field.
- EEO: use values from profile (gender, race_ethnicity, veteran_status,
  disability_status). If profile is missing one, use "Decline to answer".
- Work auth / sponsorship: read work_authorization + requires_sponsorship
  from profile.
- Phone: E.164 format when possible (e.g. +15551234567).
- Location dropdown: use user's nearest metro (profile.city, profile.state).
- Email: prefer the answer_key's text_fields.email if set, else user email.
- Dropdowns: provide `search` text that will match a visible option
  (case-insensitive substring).
- Select (native <select>): provide exact `value` text.
- Radios/checkboxes: only include refs you actually want to click. Do NOT
  include "I agree to terms" unless the app will reject without it.
- Upload_ref: the ref of the "Attach resume" / "Upload" button (never the
  file input itself — click the button to open picker).
- Submit_ref: the ref of the final submit (NOT "Next" unless this is the
  only/last page).
- If the form has a "Next" button and this is clearly step 1 of N, set
  submit_ref to the Next button's ref — the driver re-snapshots after
  and calls you again for step 2.
- For non-normal states, set fills/selects/dropdowns/radios/checkboxes
  to [] and submit_ref to null. Only `page_state`, `action`, `reason`
  matter.
"""


def plan_form_fill(
    *,
    company: str,
    role: str,
    profile_summary: str,
    answer_key: dict,
    snapshot_text: str,
    jd_hint: str = "",
) -> dict | None:
    """Ask Claude for a fill plan. Returns parsed JSON dict or None.

    None means the caller should fall back to its legacy regex path.
    """
    if not claude_available():
        return None
    prompt = build_fill_prompt(
        company=company, role=role, profile_summary=profile_summary,
        answer_key=answer_key, snapshot_text=snapshot_text, jd_hint=jd_hint,
    )
    reply = call_claude(prompt, timeout_s=45)
    if not reply:
        return None
    plan = parse_json_reply(reply)
    if plan is None:
        logger.warning("Claude reply wasn't parseable JSON — falling back to legacy")
        logger.debug(f"raw reply head: {reply[:400]}")
    return plan


def execute_fill_plan(
    plan: dict,
    *,
    resume_path: str | None,
    browser_fns: dict[str, Callable[..., Any]],
) -> None:
    """Execute the LLM plan via the applier's browser helper callbacks.

    browser_fns must supply: fill_fields, click_ref, select_option,
    upload_file, snapshot, parse_snapshot. This module stays pure-logic;
    it never imports OpenClaw wrappers directly so tests can inject
    fakes.
    """
    import time as _t

    fill_fields = browser_fns["fill_fields"]
    click_ref = browser_fns["click_ref"]
    select_option = browser_fns["select_option"]
    upload_file = browser_fns["upload_file"]
    snapshot = browser_fns.get("snapshot")
    parse_snapshot = browser_fns.get("parse_snapshot")

    # Text fields — batch in one call to avoid ref drift
    text_fills = [
        {"ref": f["ref"], "type": "textbox", "value": str(f.get("value", ""))}
        for f in plan.get("fills", []) or []
        if f.get("ref") and f.get("value") is not None
    ]
    if text_fills:
        try:
            fill_fields(json.dumps(text_fills))
            logger.info(f"LLM fill: {len(text_fills)} text fields")
        except Exception as e:
            logger.warning(f"fill_fields failed: {e}")

    # Native <select>
    for item in plan.get("selects", []) or []:
        ref, val = item.get("ref"), item.get("value") or item.get("search")
        if ref and val:
            try:
                select_option(ref, val)
                _t.sleep(0.2)
            except Exception as e:
                logger.debug(f"select {ref}={val!r}: {e}")

    # Combobox / ARIA dropdowns — click → pick matching option
    for item in plan.get("dropdowns", []) or []:
        ref, search = item.get("ref"), item.get("search") or item.get("value")
        if not (ref and search):
            continue
        try:
            click_ref(ref)
            _t.sleep(0.4)
            if snapshot and parse_snapshot:
                raw = snapshot() or ""
                opts = parse_snapshot(raw)
                matched = False
                for opt in opts:
                    if search.lower() in (opt.get("label") or "").lower():
                        click_ref(opt["ref"])
                        _t.sleep(0.2)
                        matched = True
                        break
                if not matched:
                    logger.debug(f"dropdown {ref}: no option matched {search!r}")
        except Exception as e:
            logger.debug(f"dropdown {ref}: {e}")

    # Radios
    for item in plan.get("radios", []) or []:
        ref = item.get("ref") if isinstance(item, dict) else item
        if ref:
            try:
                click_ref(ref)
                _t.sleep(0.2)
            except Exception as e:
                logger.debug(f"radio {ref}: {e}")

    # Checkboxes
    for item in plan.get("checkboxes", []) or []:
        ref = item.get("ref") if isinstance(item, dict) else item
        if ref:
            try:
                click_ref(ref)
                _t.sleep(0.2)
            except Exception as e:
                logger.debug(f"checkbox {ref}: {e}")

    # Resume upload
    upload_ref = plan.get("upload_ref")
    if upload_ref and resume_path:
        try:
            upload_file(resume_path, upload_ref)
            _t.sleep(2)
        except Exception as e:
            logger.warning(f"resume upload to {upload_ref} failed: {e}")

    # Custom JS — Claude's escape hatch for React controlled components,
    # masked fields, shadow DOM, synthetic events. Each snippet is run
    # via OpenClaw `browser evaluate` in the page context. Errors
    # swallowed so a bad script doesn't abort the whole fill.
    custom_js = plan.get("custom_js") or []
    evaluate_js = browser_fns.get("evaluate_js")
    if custom_js and evaluate_js:
        for i, snippet in enumerate(custom_js):
            if not isinstance(snippet, str) or not snippet.strip():
                continue
            if len(snippet) > 2000:
                logger.warning(f"custom_js[{i}] too long ({len(snippet)}c), skipping")
                continue
            try:
                evaluate_js(snippet)
                _t.sleep(0.3)
                logger.info(f"custom_js[{i}]: executed ({len(snippet)}c)")
            except Exception as e:
                logger.debug(f"custom_js[{i}] failed: {e}")


def llm_first_apply(
    *,
    apply_url: str,
    company_hint: str,
    profile_summary: str,
    answer_key: dict,
    resume_path: str | None,
    browser_fns: dict[str, Callable[..., Any]],
    ats_name: str,
    max_steps: int = 3,
):
    """Claude-driven end-to-end apply. Returns ApplyResult-compatible dict
    with keys `success`, `screenshot`, `error`, `retriable` OR None if
    Claude is unavailable and the caller should fall back to its legacy
    regex path.

    Multi-step-aware: if after clicking the plan's submit_ref the page
    changes but no confirmation banner shows, we re-snapshot and call
    Claude again (up to `max_steps` times) — Workday, SR screening pages,
    etc. Final success = positive confirmation text (thank you / received).
    """
    if not claude_available():
        return None

    # Late import to avoid circular
    from .base import is_submission_confirmed

    navigate_url = browser_fns["navigate_url"]
    wait_load = browser_fns["wait_load"]
    snapshot = browser_fns["snapshot"]
    take_screenshot = browser_fns["take_screenshot"]
    click_ref = browser_fns["click_ref"]

    try:
        navigate_url(apply_url)
        wait_load(5000)
        import time as _t
        _t.sleep(1)

        for step in range(max_steps):
            raw = snapshot() or ""
            if not raw:
                return {
                    "success": False, "screenshot": None,
                    "error": "no snapshot at step " + str(step + 1),
                    "retriable": True,
                }
            plan = plan_form_fill(
                company=company_hint or "",
                role="",  # Claude infers from the form; we could pass job title here
                profile_summary=profile_summary,
                answer_key=answer_key,
                snapshot_text=raw,
            )
            if plan is None:
                logger.warning(f"{ats_name}: Claude unavailable mid-flow")
                return {
                    "success": False, "screenshot": take_screenshot(),
                    "error": "claude unavailable during multi-step fill",
                    "retriable": True,
                }

            # Claude's decision branch. Takes the plan's `action` field
            # and maps it to a driver outcome. Only "fill_and_submit"
            # proceeds with the form; all others short-circuit.
            action = str(plan.get("action") or "fill_and_submit")
            page_state = str(plan.get("page_state") or "normal")
            reason = str(plan.get("reason") or "")
            logger.info(
                f"{ats_name} step {step + 1}/{max_steps}: "
                f"page_state={page_state} action={action} "
                f"reason={reason[:80]!r}"
            )

            if action == "skip_non_retriable":
                return {
                    "success": False, "screenshot": take_screenshot(),
                    "error": f"skip:{page_state}:{reason[:120]}",
                    "retriable": False,
                }
            if action == "wait_retry":
                return {
                    "success": False, "screenshot": take_screenshot(),
                    "error": f"retry:{page_state}:{reason[:120]}",
                    "retriable": True,
                }
            if action == "attempt_account_creation":
                # Out of llm_first_apply scope — surface the signal so
                # the worker (or a future Workday-specific path) can
                # handle account creation. For now, skip non-retriable.
                return {
                    "success": False, "screenshot": take_screenshot(),
                    "error": f"needs_account_creation:{reason[:120]}",
                    "retriable": False,
                }
            if action == "search_direct_url":
                # Signal to the worker that the LinkedIn/aggregator URL
                # can't be applied to directly. The existing LinkedIn
                # skip path handles it at the worker level (commit
                # 0b4c55d's resolver).
                return {
                    "success": False, "screenshot": take_screenshot(),
                    "error": f"needs_direct_url:{reason[:120]}",
                    "retriable": False,
                }
            # Default: fill_and_submit
            logger.info(
                f"  fills={len(plan.get('fills', []) or [])} "
                f"dropdowns={len(plan.get('dropdowns', []) or [])} "
                f"custom_js={len(plan.get('custom_js', []) or [])} "
                f"submit_ref={plan.get('submit_ref')!r}"
            )
            try:
                execute_fill_plan(plan, resume_path=resume_path, browser_fns=browser_fns)
            except Exception as e:
                logger.warning(f"{ats_name}: plan execution failed: {e}")

            submit_ref = plan.get("submit_ref")
            if not submit_ref:
                return {
                    "success": False, "screenshot": take_screenshot(),
                    "error": "claude returned no submit_ref",
                    "retriable": False,
                }
            try:
                click_ref(submit_ref)
            except Exception as e:
                return {
                    "success": False, "screenshot": take_screenshot(),
                    "error": f"submit click failed: {e}",
                    "retriable": True,
                }
            _t.sleep(3)
            try:
                wait_load(5000)
            except Exception:
                pass

            post = snapshot() or ""
            if is_submission_confirmed(post):
                return {
                    "success": True, "screenshot": take_screenshot(),
                    "error": None, "retriable": False,
                }
            # No confirmation yet — may be multi-step. Loop back; next
            # plan_form_fill call will see the post-submit page and
            # decide (could be step 2 of a wizard, or could be an
            # error/captcha state now exposed).

        # Exhausted max_steps without confirmation
        return {
            "success": False, "screenshot": take_screenshot(),
            "error": f"no confirmation after {max_steps} Claude-driven steps",
            "retriable": False,
        }
    except Exception as e:
        logger.exception(f"{ats_name}: llm_first_apply crashed")
        try:
            img = take_screenshot()
        except Exception:
            img = None
        return {
            "success": False, "screenshot": img,
            "error": f"llm_first_apply exception: {e}",
            "retriable": True,
        }
