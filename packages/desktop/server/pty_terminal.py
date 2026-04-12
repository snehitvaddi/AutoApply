"""
Real interactive PTY terminal for the browser.

Spawns `claude --dangerously-skip-permissions` in a real pseudo-terminal.
Bridges PTY I/O to WebSocket — user can type, see output, just like a real terminal.
Session persists across page refreshes (reconnect gets buffer backfill).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from collections import deque
from pathlib import Path

# Platform-aware PTY backend — Unix uses pty.fork() + fcntl + termios,
# Windows uses pywinpty (ConPTY). The rest of this file doesn't know
# which platform it's on.
from .pty_backend import PlatformPTY

from fastapi import WebSocket, WebSocketDisconnect

from .config import load_token, WORKSPACE_DIR

logger = logging.getLogger(__name__)

MAX_BUFFER = 50000  # characters of scrollback


class SessionRecord:
    """Track a single session's lifecycle."""
    def __init__(self, pid: int):
        self.session_id = str(uuid.uuid4())[:8]
        self.pid = pid
        self.started_at = time.time()
        self.stopped_at: float | None = None
        self.status = "running"

    def stop(self):
        self.stopped_at = time.time()
        self.status = "stopped"

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "pid": self.pid,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "status": self.status,
            "duration": (self.stopped_at or time.time()) - self.started_at,
        }


# Global session history
session_history: list[SessionRecord] = []


class PTYSession:
    """A persistent PTY session running claude --dangerously-skip-permissions.

    Nudge behavior (Part 2 mission-driven redesign):
      - _watchdog_loop: ticks every 5 min, fires a dynamic nudge when
        progress drifts (applied-today flat, scout overdue, worker dead,
        PTY idle). Never gated on PTY byte flow alone.

    Writes to the PTY via /btw so Claude processes nudges as side-channel
    messages instead of user turns. \\r terminator is CRITICAL — the TUI
    runs in raw mode and \\n alone leaves the text sitting in the input
    buffer un-submitted.

    When everything is running fine → the watchdog stays silent, zero messages.
    Only fires when something is actually stuck.
    """

    # Tick intervals
    WATCHDOG_INTERVAL = 300            # 5 min — mission drift check
    # Drift thresholds
    IDLE_THRESHOLD = 1800              # 30 min — PTY silence
    SCOUT_STALE_MULTIPLIER = 2         # 2x SCOUT_INTERVAL_MINUTES = overdue
    NUDGE_COOLDOWN = 600               # 10 min min between nudges
    STUCK_APPLIED_CYCLES = 3           # 3 x 5min = 15 min flat applied count

    def __init__(self):
        self._pty: PlatformPTY | None = None  # platform-aware PTY backend
        self.master_fd: int | None = None     # kept for backward compat (Unix only)
        self.child_pid: int | None = None
        self.output_buffer: deque[bytes] = deque(maxlen=MAX_BUFFER)
        self._subscribers: list[asyncio.Queue] = []
        self._read_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._alive = False
        self.session_id: str | None = None
        self.last_output_at: float = 0
        self.started_at: float = 0

        # Mission/tenant state — populated lazily at session start via
        # _refresh_tenant_context(). May be None if the cloud is unreachable
        # or the user hasn't finished setup; in that case the heartbeat
        # loop still fires with a "finish setup" message instead of crashing.
        self._tenant_snapshot: dict | None = None
        self._last_nudge_at: float = 0
        self._last_applied_count: int | None = None
        self._stuck_cycles: int = 0

    @property
    def is_alive(self) -> bool:
        if not self._alive or self._pty is None:
            return False
        try:
            if not self._pty.is_alive():
                self._alive = False
                return False
            return True
        except Exception:
            self._alive = False
            return False

    def status(self) -> dict:
        idle_seconds = (time.time() - self.last_output_at) if self.last_output_at else 0
        return {
            "session_id": self.session_id,
            "alive": self.is_alive,
            "pid": self.child_pid,
            "buffer_size": sum(len(b) for b in self.output_buffer),
            "subscribers": len(self._subscribers),
            "uptime": (time.time() - self.started_at) if self.started_at and self.is_alive else 0,
            "idle_seconds": idle_seconds if self.is_alive else 0,
            "idle_minutes": int(idle_seconds / 60) if self.is_alive else 0,
        }

    @staticmethod
    def _find_claude() -> str | None:
        """Find claude binary — cross-platform."""
        claude = shutil.which("claude")
        if claude:
            return claude
        candidates = []
        if sys.platform == "win32":
            # Windows: check npm global, AppData, Program Files
            candidates = [
                os.path.expandvars(r"%APPDATA%\npm\claude.cmd"),
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\claude\claude.exe"),
                os.path.expandvars(r"%PROGRAMFILES%\Claude\claude.exe"),
                os.path.expanduser(r"~\.local\bin\claude.exe"),
            ]
        else:
            # Mac/Linux
            candidates = [
                os.path.expanduser("~/.local/bin/claude"),
                "/usr/local/bin/claude",
                "/opt/homebrew/bin/claude",
                os.path.expanduser("~/.npm-global/bin/claude"),
            ]
        for p in candidates:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        return None

    @staticmethod
    def _push_integrations_from_env_to_cloud(cwd: str, env: dict) -> int:
        """Walk local .env for the 6 integration keys; for any key that is
        non-empty locally AND not already set on the cloud, validate it
        against the server's regex rules and PUT it up. Returns the count
        of fields successfully pushed.

        This is the reverse of _sync_integrations_to_env: we already had
        cloud → local, now we add local → cloud so a user who set their
        creds via install.sh gets them into the cloud automatically on the
        first desktop launch. Prevents the "I already have all my keys in
        .env but the web dashboard shows (not set)" confusion.

        Safety:
        - Never pushes values that fail shape validation (the server would
          reject them anyway, and we don't want per-field rejection to kill
          the whole batch).
        - Never pushes placeholder strings like "placeholder", "xxx",
          "changeme" that were injected by install.sh when the user skipped
          a prompt.
        - Never overwrites a cloud value that's already set — only fills
          gaps. If the user explicitly edited on the web dashboard, that
          value is authoritative.
        """
        import re as _re_push
        import urllib.request, urllib.error

        token = (env.get("WORKER_TOKEN") or "").strip().strip('"').strip("'")
        if not token:
            return 0
        app_url = os.environ.get("APPLYLOOP_APP_URL", "https://applyloop.vercel.app")

        # First, check what cloud already has so we only fill gaps.
        try:
            req = urllib.request.Request(
                f"{app_url}/api/settings/integrations",
                headers={"X-Worker-Token": token},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                current = (json.loads(resp.read()) or {}).get("data", {}).get("integrations", {})
        except Exception as e:
            logger.info(f"Integration push skipped (can't read current state): {e}")
            return 0

        # Shape validators mirroring /api/settings/integrations/route.ts.
        PLACEHOLDERS = {"placeholder", "changeme", "todo", "xxx", "your_token_here", ""}
        def valid(key: str, value: str) -> bool:
            if not value or value.lower() in PLACEHOLDERS:
                return False
            if key == "telegram_bot_token":
                return bool(_re_push.match(r"^[0-9]{6,}:[A-Za-z0-9_-]{25,}$", value))
            if key == "telegram_chat_id":
                return bool(_re_push.match(r"^-?[0-9]+$", value))
            if key == "gmail_email":
                return bool(_re_push.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", value))
            if key == "gmail_app_password":
                return len(value.replace(" ", "")) == 16
            if key in ("agentmail_api_key", "finetune_resume_api_key"):
                return len(value) >= 8
            return False

        env_to_cloud_key = {
            "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
            "TELEGRAM_CHAT_ID": "telegram_chat_id",
            "GMAIL_EMAIL": "gmail_email",
            "GMAIL_APP_PASSWORD": "gmail_app_password",
            "AGENTMAIL_API_KEY": "agentmail_api_key",
            "FINETUNE_RESUME_API_KEY": "finetune_resume_api_key",
        }
        payload: dict[str, str] = {}
        skipped_invalid: list[str] = []
        skipped_already_set: list[str] = []
        for env_key, cloud_key in env_to_cloud_key.items():
            local_val = (env.get(env_key) or "").strip()
            if not local_val:
                continue
            if current.get(cloud_key, {}).get("set"):
                skipped_already_set.append(cloud_key)
                continue
            if not valid(cloud_key, local_val):
                skipped_invalid.append(cloud_key)
                continue
            payload[cloud_key] = local_val

        if not payload:
            if skipped_invalid:
                logger.info(
                    f"Integration push: nothing to sync. Skipped "
                    f"(invalid/placeholder): {', '.join(skipped_invalid)}. "
                    f"Update these via the Integrations tab or install.sh."
                )
            return 0

        try:
            body = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{app_url}/api/settings/integrations",
                data=body,
                method="PUT",
                headers={
                    "X-Worker-Token": token,
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            msg = f"Pushed {len(payload)} integration key(s) from local .env to cloud: {', '.join(payload.keys())}"
            if skipped_invalid:
                msg += f" (skipped invalid: {', '.join(skipped_invalid)})"
            logger.info(msg)
            return len(payload)
        except Exception as e:
            logger.warning(f"Integration push failed: {e}")
            return 0

    @staticmethod
    def _sync_integrations_to_env(cwd: str, env: dict) -> bool:
        """Pull encrypted integration credentials from
        /api/settings/integrations?raw=1 (Telegram bot/chat, Gmail
        email/app_password, AgentMail, Finetune Resume) and write the
        decrypted plaintext into ~/.applyloop/.env.

        Strategy: read the existing .env line-by-line, replace any line
        starting with one of the integration keys, leave everything else
        untouched. Cloud wins on non-empty. If the cloud has nothing set
        for a key, the existing .env value is preserved (so wiping the
        cloud doesn't accidentally wipe a working local .env).

        Best-effort: any failure just logs + returns False. The session
        still boots with whatever was already in .env.
        """
        import urllib.request
        token = (env.get("WORKER_TOKEN") or "").strip().strip('"').strip("'")
        if not token:
            return False
        app_url = os.environ.get("APPLYLOOP_APP_URL", "https://applyloop.vercel.app")
        try:
            req = urllib.request.Request(
                f"{app_url}/api/settings/integrations?raw=1",
                headers={"X-Worker-Token": token},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read()) or {}
        except Exception as e:
            # Migration 010 not applied yet → server returns 500 with a
            # clear message. Log at info so it's visible but not alarming.
            logger.info(f"Integrations sync skipped: {e}")
            return False

        data = payload.get("data") or {}
        integrations = data.get("integrations") or {}
        if not integrations:
            return False

        # Only these keys are written to .env. Anything else the endpoint
        # might return is ignored.
        key_map = {
            "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
            "telegram_chat_id": "TELEGRAM_CHAT_ID",
            "gmail_email": "GMAIL_EMAIL",
            "gmail_app_password": "GMAIL_APP_PASSWORD",
            "agentmail_api_key": "AGENTMAIL_API_KEY",
            "finetune_resume_api_key": "FINETUNE_RESUME_API_KEY",
        }

        # Build the set of (env_key → new_value) pairs for cloud values
        # that are non-empty. Empty cloud values DON'T clear the .env —
        # that's explicit via the "clear" button in the Integrations tab,
        # which sends the key with an empty string and the server drops
        # it from the encrypted blob (so it'd re-appear here as absent).
        updates: dict[str, str] = {}
        for src, dst in key_map.items():
            v = integrations.get(src) or ""
            if v:
                updates[dst] = v

        if not updates:
            return False

        env_path = os.path.join(cwd, ".env")
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = []
        except Exception as e:
            logger.warning(f"Could not read .env for integrations sync: {e}")
            return False

        # In-place rewrite: replace existing lines that start with a
        # known key, append missing ones at the bottom.
        seen: set[str] = set()
        new_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in updates:
                    new_lines.append(f"{key}={updates[key]}\n")
                    seen.add(key)
                    continue
            new_lines.append(line)

        # Append any keys that weren't in the original .env
        for key, val in updates.items():
            if key not in seen:
                if new_lines and not new_lines[-1].endswith("\n"):
                    new_lines.append("\n")
                new_lines.append(f"{key}={val}\n")

        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            logger.info(f"Synced {len(updates)} integration key(s) from cloud to .env: {', '.join(updates.keys())}")
            # Also update the in-memory env dict so the rest of
            # _read_profile_snapshot sees the fresh values (e.g. for the
            # live Telegram probe).
            for k, v in updates.items():
                env[k] = v
            return True
        except Exception as e:
            logger.warning(f"Could not write .env during integrations sync: {e}")
            return False

    @staticmethod
    def _download_resume_locally(env: dict) -> str | None:
        """Fetch the user's default resume PDF from the cloud and stash it
        at ~/.autoapply/workspace/resumes/default.pdf so the Claude PTY
        session can read it with its built-in Read tool.

        This is how we turn the resume parser into a local, free-of-third-
        party-keys flow: instead of calling a Vercel endpoint that needs an
        OpenAI key, we let the user's already-authenticated Claude Code CLI
        (their Max subscription) read the PDF directly and PUT the
        structured result back to /api/settings/profile. Much cleaner
        architecture — no extra LLM dependency, and the user pays for it
        via their existing Claude plan.

        Returns the local path on success, None on failure. Idempotent:
        re-downloads every session start so the local file mirrors
        whatever's on Supabase (handles the "user replaced their resume"
        case without a marker-invalidation dance).
        """
        import urllib.request
        token = (env.get("WORKER_TOKEN") or "").strip().strip('"').strip("'")
        if not token:
            return None
        app_url = os.environ.get("APPLYLOOP_APP_URL", "https://applyloop.vercel.app")
        target_dir = os.path.expanduser("~/.autoapply/workspace/resumes")
        target = os.path.join(target_dir, "default.pdf")
        try:
            os.makedirs(target_dir, exist_ok=True)
            req = urllib.request.Request(
                f"{app_url}/api/onboarding/resume/download",
                headers={"X-Worker-Token": token},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read()
            # Sanity: must be a real PDF (4-byte magic).
            if not body.startswith(b"%PDF"):
                logger.warning(
                    f"Resume download returned non-PDF bytes ({len(body)}B) — not caching"
                )
                return None
            with open(target, "wb") as f:
                f.write(body)
            logger.info(f"Resume cached locally: {target} ({len(body)}B)")
            return target
        except Exception as e:
            logger.warning(f"Resume download failed: {e}")
            return None

    @staticmethod
    def _profile_is_stub(profile: dict) -> bool:
        """True when the profile looks like it came from the cli-config
        synthesis fallback alone (one work_experience entry with empty
        achievements and empty skills[]) — i.e. the onboarding form
        captured only the flat fields and the PDF was never parsed."""
        exp = profile.get("experience") or []
        if not exp:
            return True
        if len(exp) == 1:
            e0 = exp[0] or {}
            if not (e0.get("achievements") or []):
                return True
        skills = profile.get("skills") or []
        if not skills:
            return True
        return False

    @staticmethod
    def _load_sync_meta(cwd: str) -> dict:
        """Sibling file that records when we last pulled/pushed and which
        fields failed to push. Lives next to profile.json so it survives
        across sessions."""
        path = os.path.join(cwd, ".profile-sync.meta.json")
        if not os.path.isfile(path):
            return {"last_pull_at": 0, "last_push_at": 0, "last_cloud_updated_at": "", "failed_push_fields": []}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {"last_pull_at": 0, "last_push_at": 0, "last_cloud_updated_at": "", "failed_push_fields": []}

    @staticmethod
    def _save_sync_meta(cwd: str, meta: dict) -> None:
        path = os.path.join(cwd, ".profile-sync.meta.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not write sync meta: {e}")

    @staticmethod
    def _pull_profile_from_cloud(cwd: str, env: dict) -> bool:
        """Sync profile.json FROM the cloud on every session start.

        This is what makes "cloud is source of truth" real: every PTY spawn
        re-hydrates local profile.json from /api/settings/cli-config, so
        anything the user changed on applyloop.vercel.app (or anything Claude
        pushed from a previous session) is reflected in this session.

        Merge policy: cloud wins on any field that cloud has non-empty;
        local preserves anything cloud hasn't set yet.

        Best-effort: network failures log a warning and leave the file alone
        so the session still boots offline."""
        import urllib.request
        token = (env.get("WORKER_TOKEN") or "").strip().strip('"').strip("'")
        if not token:
            return False
        app_url = os.environ.get("APPLYLOOP_APP_URL", "https://applyloop.vercel.app")
        try:
            req = urllib.request.Request(
                f"{app_url}/api/settings/cli-config",
                headers={"X-Worker-Token": token},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read()) or {}
        except Exception as e:
            logger.warning(f"Cloud profile pull failed: {e}")
            return False

        data = payload.get("data") or {}
        cloud_profile = data.get("profile") or {}
        cloud_prefs = data.get("preferences") or {}
        cloud_user = data.get("user") or {}
        if not cloud_profile and not cloud_prefs:
            return False

        profile_path = os.path.join(cwd, "profile.json")
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                local = json.load(f) or {}
        except Exception:
            local = {}

        # Sync metadata for conflict detection. If the cloud row's
        # updated_at advanced AND we have local-only changes pending,
        # we'd be overwriting someone else's edit. Log it loudly — we
        # still apply cloud-wins semantics, but the warning tells us
        # sync is contested so we can act on it upstream.
        meta = PTYSession._load_sync_meta(cwd)
        cloud_updated_at = cloud_profile.get("updated_at") or ""
        if (
            meta.get("last_cloud_updated_at")
            and cloud_updated_at
            and cloud_updated_at > meta["last_cloud_updated_at"]
            and meta.get("failed_push_fields")
        ):
            logger.warning(
                f"Sync conflict: cloud advanced from {meta['last_cloud_updated_at']} to "
                f"{cloud_updated_at} while local had pending unpushed fields "
                f"{meta['failed_push_fields']}. Cloud wins; retrying push after merge."
            )

        # Push-delta: any field where local has non-empty data but cloud
        # doesn't. This catches data Claude collected in a previous session
        # but failed to PUT up. We'll accumulate here then PUT at the end.
        push_delta: dict = {}

        def nonempty(v) -> bool:
            if v is None: return False
            if isinstance(v, str): return bool(v.strip())
            if isinstance(v, (list, dict)): return bool(v)
            return True

        local.setdefault("user", {})
        for src, dst in (("id", "id"), ("email", "email"), ("full_name", "full_name")):
            if nonempty(cloud_user.get(src)):
                local["user"][dst] = cloud_user.get(src)
        if nonempty(data.get("tier")):
            local["user"]["tier"] = data.get("tier")

        # Three-way reconcile helper: cloud wins on non-empty, else local
        # wins and goes into the push_delta for upload.
        def reconcile(local_container: dict, local_key: str,
                      cloud_val, server_field: str):
            if nonempty(cloud_val):
                local_container[local_key] = cloud_val
            else:
                lv = local_container.get(local_key)
                if nonempty(lv):
                    push_delta[server_field] = lv

        personal = local.setdefault("personal", {})
        for k in ("first_name", "last_name", "phone", "linkedin_url",
                  "github_url", "portfolio_url"):
            reconcile(personal, k, cloud_profile.get(k), k)
        if nonempty(cloud_user.get("email")):
            personal["email"] = cloud_user.get("email")

        work = local.setdefault("work", {})
        for k in ("current_company", "current_title", "years_experience"):
            reconcile(work, k, cloud_profile.get(k), k)

        legal = local.setdefault("legal", {})
        for k in ("work_authorization", "requires_sponsorship"):
            reconcile(legal, k, cloud_profile.get(k), k)

        eeo = local.setdefault("eeo", {})
        for k in ("gender", "race_ethnicity", "veteran_status", "disability_status"):
            reconcile(eeo, k, cloud_profile.get(k), k)

        # Top-level arrays (experience/skills) + education string.
        # Server field names differ: experience → work_experience, but
        # skills and education keep their names.
        if nonempty(cloud_profile.get("work_experience")):
            local["experience"] = cloud_profile.get("work_experience")
        elif nonempty(local.get("experience")):
            push_delta["work_experience"] = local["experience"]

        if nonempty(cloud_profile.get("skills")):
            local["skills"] = cloud_profile.get("skills")
        elif nonempty(local.get("skills")):
            push_delta["skills"] = local["skills"]

        if nonempty(cloud_profile.get("education")):
            local["education"] = cloud_profile.get("education")
        elif nonempty(local.get("education")):
            push_delta["education"] = local["education"]

        edu_summary = local.setdefault("education_summary", {})
        for k in ("education_level", "school_name", "degree", "graduation_year"):
            reconcile(edu_summary, k, cloud_profile.get(k), k)

        if nonempty(cloud_profile.get("answer_key_json")):
            local["standard_answers"] = cloud_profile.get("answer_key_json")
        elif nonempty(local.get("standard_answers")):
            push_delta["answer_key_json"] = local["standard_answers"]

        if nonempty(cloud_profile.get("cover_letter_template")):
            local["cover_letter_template"] = cloud_profile.get("cover_letter_template")
        elif nonempty(local.get("cover_letter_template")):
            push_delta["cover_letter_template"] = local["cover_letter_template"]

        if cloud_prefs:
            local["preferences"] = cloud_prefs

        try:
            with open(profile_path, "w", encoding="utf-8") as f:
                json.dump(local, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not write pulled profile: {e}")
            return False

        # Push-delta: ship local-only data up to the cloud so future pulls
        # will have it. This is what reconciles prior sessions where Claude
        # wrote to local but failed the curl PUT.
        import time as _time_mod
        now = _time_mod.time()
        pushed_ok = True
        if push_delta:
            pushed_ok = PTYSession._push_profile_to_cloud(cwd, env, push_delta)
            if pushed_ok:
                logger.info(f"Synced profile: pulled cloud, pushed local delta ({len(push_delta)} fields: {', '.join(push_delta.keys())})")
                meta["failed_push_fields"] = []
                meta["last_push_at"] = now
            else:
                logger.warning(f"Pulled cloud but delta push failed for {len(push_delta)} fields")
                meta["failed_push_fields"] = list(push_delta.keys())
        else:
            logger.info("Pulled profile from cloud (local already in sync)")
            meta["failed_push_fields"] = []
        meta["last_pull_at"] = now
        meta["last_cloud_updated_at"] = cloud_updated_at
        PTYSession._save_sync_meta(cwd, meta)
        return True

    @staticmethod
    def _push_profile_to_cloud(cwd: str, env: dict, fields: dict) -> bool:
        """PUT a partial update to /api/settings/profile. Called after the
        local normalization step inferred fields the cloud didn't have, and
        available for Claude to invoke (via the prompt directive) after every
        answer it collects from the user.

        Silent on failure — never blocks the session."""
        import urllib.request
        token = (env.get("WORKER_TOKEN") or "").strip().strip('"').strip("'")
        if not token or not fields:
            return False
        app_url = os.environ.get("APPLYLOOP_APP_URL", "https://applyloop.vercel.app")
        try:
            body = json.dumps(fields).encode("utf-8")
            req = urllib.request.Request(
                f"{app_url}/api/settings/profile",
                data=body,
                method="PUT",
                headers={
                    "X-Worker-Token": token,
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
            logger.info(f"Pushed {len(fields)} field(s) to cloud profile")
            return True
        except Exception as e:
            logger.warning(f"Cloud profile push failed: {e}")
            return False

    @staticmethod
    def _normalize_profile_inplace(profile: dict) -> list:
        """Infer missing fields from data the profile already has, so Claude
        doesn't waste the user's time asking for things we can derive.

        Returns a list of field paths we populated (for logging). The profile
        dict is mutated in place. The caller writes it back to disk.

        Inference rules:
          - education_summary.education_level / .degree / .field from the
            top-level `education` string (e.g. "MS in Computer & Information
            Science" → masters / MS / Computer & Information Science).
          - experience[0] from work.current_company + work.current_title
            if experience[] is empty but the flat fields are populated
            (mirrors the server-side synthesis in /api/settings/cli-config).
        """
        populated: list[str] = []

        # `education` can be one of three shapes in the wild:
        #   (a) a plain string   — "MS in Computer & Information Science"
        #       (legacy, produced by the install-time cli-config scalar fallback)
        #   (b) a JSONB array    — [{"school": "...", "degree": "MS", "field": "..."}]
        #       (what the PDF parser writes and what migration 005 intended)
        #   (c) missing / empty
        #
        # Normalize to the string form for downstream regex inference, but
        # also feed education_summary from the structured entry when we have
        # one — it's strictly richer than regex parsing.
        edu_raw = profile.get("education")
        edu_str = ""
        edu_entry: dict = {}
        if isinstance(edu_raw, str):
            edu_str = edu_raw
        elif isinstance(edu_raw, list) and edu_raw:
            first = edu_raw[0] if isinstance(edu_raw[0], dict) else {}
            edu_entry = first
            # Synthesize a display string for any reader that still wants one.
            degree_part = first.get("degree") or ""
            field_part = first.get("field") or ""
            if degree_part and field_part:
                edu_str = f"{degree_part} in {field_part}"
            elif degree_part:
                edu_str = degree_part
            elif field_part:
                edu_str = field_part

        edu_summary = profile.setdefault("education_summary", {})

        # Structured entry wins over regex inference.
        if edu_entry and isinstance(edu_summary, dict):
            if not edu_summary.get("school_name") and edu_entry.get("school"):
                edu_summary["school_name"] = edu_entry["school"]
                populated.append(f"education_summary.school_name={edu_entry['school'][:40]}")
            if not edu_summary.get("degree") and edu_entry.get("degree"):
                edu_summary["degree"] = edu_entry["degree"]
                populated.append(f"education_summary.degree={edu_entry['degree']}")
            if not edu_summary.get("field") and edu_entry.get("field"):
                edu_summary["field"] = edu_entry["field"]
                populated.append(f"education_summary.field={edu_entry['field'][:40]}")
            # graduation_year: try end_date → parse trailing 4-digit year
            if not edu_summary.get("graduation_year"):
                import re as _re_grad
                end_date = edu_entry.get("end_date") or ""
                m_year = _re_grad.search(r"(19|20)\d{2}", str(end_date))
                if m_year:
                    edu_summary["graduation_year"] = m_year.group(0)
                    populated.append(f"education_summary.graduation_year={m_year.group(0)}")

        if edu_str and isinstance(edu_summary, dict):
            import re
            s = edu_str.strip()
            s_lower = s.lower()

            # education_level
            if not edu_summary.get("education_level"):
                if re.search(r"\b(phd|ph\.d|doctorate|doctoral)\b", s_lower):
                    edu_summary["education_level"] = "phd"
                    populated.append("education_summary.education_level=phd")
                elif re.search(r"\b(ms|m\.s|ma|m\.a|mba|master'?s?|master of)\b", s_lower):
                    edu_summary["education_level"] = "masters"
                    populated.append("education_summary.education_level=masters")
                elif re.search(r"\b(bs|b\.s|ba|b\.a|bachelor'?s?|bachelor of)\b", s_lower):
                    edu_summary["education_level"] = "bachelors"
                    populated.append("education_summary.education_level=bachelors")

            # degree (short form at start of string, before " in " / " of ")
            if not edu_summary.get("degree"):
                m = re.match(r"^\s*(MS|M\.S\.?|MA|M\.A\.?|MBA|BS|B\.S\.?|BA|B\.A\.?|PhD|Ph\.D\.?|Master'?s?|Bachelor'?s?|Doctorate)\b", s)
                if m:
                    edu_summary["degree"] = m.group(1)
                    populated.append(f"education_summary.degree={m.group(1)}")

            # field of study ("in X" / "of X")
            m = re.search(r"\b(?:in|of)\s+(.+?)(?:\s+at\s+|\s+from\s+|\s*\(|,|$)", s, re.IGNORECASE)
            if m and not edu_summary.get("field"):
                edu_summary["field"] = m.group(1).strip()
                populated.append(f"education_summary.field={m.group(1).strip()[:40]}")

        # experience[] synthesis from flat work fields
        work = profile.get("work", {}) or {}
        exp = profile.get("experience")
        current_company = work.get("current_company")
        current_title = work.get("current_title")
        if (not exp or (isinstance(exp, list) and len(exp) == 0)) and current_company:
            profile["experience"] = [{
                "company": current_company,
                "title": current_title or "",
                "location": "",
                "start_date": "",
                "end_date": "Present",
                "current": True,
                "achievements": [],
            }]
            populated.append("experience[0] from work.current_company/title")

        return populated

    @staticmethod
    def _read_profile_snapshot(cwd: str) -> dict:
        """Load profile.json + .env from the cwd and return the minimal snapshot
        the initial prompt needs. Returns {} on any read error so startup is
        never blocked by a bad profile file."""
        out: dict = {"complete": False, "missing": [], "profile": {}, "env": {}}
        try:
            # Step 1: read .env (needed for the cloud sync token).
            env_path = os.path.join(cwd, ".env")
            if os.path.isfile(env_path):
                env_pairs = {}
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        env_pairs[k.strip()] = v.strip().strip('"').strip("'")
                out["env"] = env_pairs

            # Step 2: pull the latest profile from the cloud BEFORE reading
            # the local file. This re-hydrates profile.json so any changes
            # made on applyloop.vercel.app (or pushed by a previous session)
            # are reflected in this session. Cloud is the source of truth.
            PTYSession._pull_profile_from_cloud(cwd, out["env"])

            # Step 2b: bidirectional integration sync.
            # Push first (fills any cloud gaps from local .env values the
            # user set via install.sh), then pull (pulls authoritative
            # values back down). This order matters: a push-then-pull means
            # the user ends up with whatever's on cloud AS OF the end of
            # this session start, which is the "cloud is source of truth"
            # semantics we want. If cloud already has a field set, the push
            # skips it — cloud edits never get clobbered by stale .env.
            PTYSession._push_integrations_from_env_to_cloud(cwd, out["env"])
            PTYSession._sync_integrations_to_env(cwd, out["env"])

            # Step 3: read the (now freshly-synced) local profile.
            profile_path = os.path.join(cwd, "profile.json")
            if os.path.isfile(profile_path):
                with open(profile_path, "r", encoding="utf-8") as f:
                    out["profile"] = json.load(f) or {}

            # Step 3.5: download the user's resume PDF locally EVERY
            # session so Claude can always read it via its built-in Read
            # tool. No marker/sentinel — we always refresh, so if the user
            # replaces their resume the next session picks up the new one
            # automatically. Also records the path so the initial prompt
            # can inject it into the self-heal instructions.
            local_resume = PTYSession._download_resume_locally(out["env"])
            out["resume_path"] = local_resume or ""
        except Exception as e:
            logger.warning(f"profile snapshot read failed: {e}")
            return out

        # Pre-infer fields Claude would otherwise ask about, so we don't
        # waste the user's time on things the existing profile already
        # implies (e.g. education_level="masters" from education="MS in ...").
        p = out["profile"]
        if p:
            try:
                inferred = PTYSession._normalize_profile_inplace(p)
                if inferred:
                    profile_path = os.path.join(cwd, "profile.json")
                    try:
                        with open(profile_path, "w", encoding="utf-8") as f:
                            json.dump(p, f, indent=2)
                        logger.info(f"Pre-inferred profile fields: {', '.join(inferred)}")
                    except Exception as e:
                        logger.warning(f"Could not persist inferred profile: {e}")
                    # Push the inferred fields up to the cloud so the pull
                    # side stays authoritative. Only push the subset we
                    # actually inferred, mapped to server field names.
                    edu = (p.get("education_summary") or {})
                    patch: dict = {}
                    if edu.get("education_level"):
                        patch["education_level"] = edu["education_level"]
                    if edu.get("degree"):
                        patch["degree"] = edu["degree"]
                    if edu.get("school_name"):
                        patch["school_name"] = edu["school_name"]
                    if edu.get("graduation_year"):
                        patch["graduation_year"] = edu["graduation_year"]
                    if patch:
                        PTYSession._push_profile_to_cloud(cwd, out["env"], patch)
            except Exception as e:
                logger.warning(f"Profile normalization failed: {e}")

        missing: list[str] = []
        personal = p.get("personal", {}) or {}
        if not personal.get("first_name"):
            missing.append("personal.first_name")
        work = p.get("work", {}) or {}
        if not work.get("current_company"):
            missing.append("work.current_company")
        if not p.get("experience"):
            missing.append("experience[]")
        if not p.get("skills"):
            missing.append("skills[]")
        edu = p.get("education_summary", {}) or {}
        for k in ("education_level", "school_name", "degree", "graduation_year"):
            if not edu.get(k):
                missing.append(f"education_summary.{k}")
                break  # one is enough to flag
        eeo = p.get("eeo", {}) or {}
        for k in ("gender", "race_ethnicity", "veteran_status", "disability_status"):
            if not eeo.get(k):
                missing.append(f"eeo.{k}")
                break
        prefs = p.get("preferences", {}) or {}
        if not prefs.get("target_titles"):
            missing.append("preferences.target_titles")
        out["missing"] = missing
        out["complete"] = len(missing) == 0
        return out

    @staticmethod
    def _build_initial_prompt(cwd: str, snapshot: dict) -> str:
        """Construct the personalized, auto-start-capable prompt Claude sees
        at session boot. Branches on whether profile.json is complete:

          - complete  → Claude fires a Telegram startup announce, then kicks
                        off the scout loop immediately without waiting for
                        'start'.
          - incomplete → Claude first collects the missing fields from the
                        user interactively, PATCHes them to
                        /api/settings/profile, rewrites ~/.applyloop/profile.json,
                        then fires the same Telegram announce and auto-starts.
        """
        p = snapshot.get("profile", {}) or {}
        env = snapshot.get("env", {}) or {}
        personal = p.get("personal", {}) or {}
        work = p.get("work", {}) or {}
        prefs = p.get("preferences", {}) or {}

        first_name = personal.get("first_name") or "there"
        current_company = work.get("current_company") or "unknown company"
        current_title = work.get("current_title") or "unknown role"
        target_titles = ", ".join((prefs.get("target_titles") or [])[:6]) or "roles listed in profile.json"

        # A real Telegram bot token is ~45+ chars in the shape
        # "<bot_id>:<secret>" — anything shorter (e.g. "placeholder") is
        # a stub from an incomplete admin-side config. Treat stubs as
        # absent so Claude doesn't try to curl a 404.
        tg_bot_raw = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
        tg_chat = (env.get("TELEGRAM_CHAT_ID") or "").strip()
        tg_bot_real = len(tg_bot_raw) >= 30 and ":" in tg_bot_raw
        tg_bot = tg_bot_raw if tg_bot_real else ""
        # Live probe: only flag tg_available after verifying the bot token
        # and chat_id actually work against api.telegram.org. This catches
        # revoked tokens, banned bots, or chat_ids the user pasted from
        # another account. Best-effort; the probe has a 3s timeout so a
        # flaky network never blocks session start.
        tg_available = False
        if tg_bot and tg_chat:
            try:
                import urllib.request, urllib.parse
                test_body = urllib.parse.urlencode({
                    "chat_id": tg_chat,
                    "text": "[ApplyLoop] Session starting…",
                }).encode()
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{tg_bot}/sendMessage",
                    data=test_body,
                    method="POST",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    if resp.status == 200:
                        tg_available = True
                        logger.info("Telegram probe ok — sendMessage returned 200")
            except Exception as e:
                logger.info(f"Telegram probe failed — disabling telegram announce this session: {e}")

        missing = snapshot.get("missing", [])
        is_complete = snapshot.get("complete", False)
        resume_path = snapshot.get("resume_path") or ""
        profile_stub = PTYSession._profile_is_stub(p)

        preferred_locations = ", ".join((prefs.get("preferred_locations") or [])[:3]) or "any"

        lines: list[str] = []
        lines.append("You are the ApplyLoop agent booting fresh for the user.")
        lines.append(f"User: {first_name} — currently {current_title} at {current_company}.")
        lines.append(f"Target roles: {target_titles}.")
        lines.append(f"Preferred locations: {preferred_locations}.")
        lines.append("")
        lines.append("MISSION STATEMENT — internalize this and never deviate:")
        lines.append(
            "  Your ONLY mission is to keep the scout → filter → apply loop "
            "running 24/7 for THIS tenant."
        )
        lines.append(
            "  Not for admin. Not for AI/ML roles unless that's what this "
            "tenant's target_titles say. Not for US locations unless that's "
            "in their preferred_locations."
        )
        lines.append(
            "  Every query, every filter, every form-fill uses THIS tenant's "
            "data — the profile.json under ~/.applyloop/, which is a local "
            "cache of their cloud profile."
        )
        lines.append(
            "  The worker.py process does the mechanical scouting and "
            "applying. Your job is to keep it alive: start it, restart it "
            "when it dies, respond to user messages, and always keep the "
            "loop moving. A watchdog checks every 5 min if progress has "
            "stalled — if the worker dies, scout is overdue, or applied "
            "count stops growing with jobs in queue, it will nudge you "
            "with the exact next action to take. Act on those nudges."
        )
        lines.append("")
        lines.append("USER COMMANDS (via /btw from chat UI or Telegram):")
        lines.append(
            "  Messages prefixed with 'USER COMMAND' are direct instructions from "
            "the user — from the chat UI or Telegram. You MUST act on them, not "
            "just acknowledge. Examples:"
        )
        lines.append(
            "    'stop scouting' → kill the worker subprocess, confirm it stopped"
        )
        lines.append(
            "    'start applying' → run the worker if it's not running"
        )
        lines.append(
            "    'apply only to Stripe' → adjust the filter, scout Stripe jobs"
        )
        lines.append(
            "    'skip this job' → mark current job as skipped, move to next"
        )
        lines.append(
            "    'pause for 2 hours' → stop the worker, set a reminder, restart later"
        )
        lines.append(
            "  After executing, confirm what you did in 1-2 lines. The response "
            "goes back to the user via the same channel (chat or Telegram)."
        )
        lines.append("")
        lines.append("ARCHITECTURE RULE — read once, apply everywhere:")
        lines.append("  The SINGLE SOURCE OF TRUTH is the cloud profile at applyloop.vercel.app.")
        lines.append("  Local ./profile.json is a CACHE — it was just re-pulled from the cloud")
        lines.append("  before this session started. NEVER treat local as authoritative.")
        lines.append("  Every profile change MUST be PUT to the server FIRST. Updating local")
        lines.append("  only is forbidden — it will be overwritten on next boot.")
        lines.append("")
        lines.append("Playbook: ./packages/worker/SOUL.md.")
        lines.append("")

        worker_token_hint = "$(grep ^WORKER_TOKEN= ./.env | cut -d= -f2- | tr -d '\"')"

        # If the profile is stub-only AND the user's resume PDF is sitting
        # locally, the fastest path is: use your own Read tool to parse the
        # PDF, extract multi-entry work_experience/skills/education, and
        # PUT it all to /api/settings/profile in one call. This replaces
        # asking the user for each field and saves them 10 minutes of typing.
        if profile_stub and resume_path and os.path.isfile(resume_path):
            lines.append("RESUME PARSE SHORTCUT — do this FIRST, before anything else:")
            lines.append("")
            lines.append(f"  The user's resume PDF is at: {resume_path}")
            lines.append(f"  Use your Read tool on {resume_path} to load the PDF, then")
            lines.append("  extract the following into the profile.json schema shape —")
            lines.append("  extract EVERYTHING, not a summary:")
            lines.append("")
            lines.append("  1. work_experience[]: EVERY job on the resume, most recent first")
            lines.append("     - Full legal company name (e.g. 'Modernizing Medicine, Inc.', not 'ModMed')")
            lines.append("     - Exact title as written, start/end dates in 'Mon YYYY' format")
            lines.append("     - At least 3 achievement bullets per role, verbatim — no paraphrasing")
            lines.append("")
            lines.append("  2. education[]: EVERY school — undergrad AND grad AND doctoral")
            lines.append("     - Full school name (e.g. 'University of Florida', not 'UF')")
            lines.append("     - Full degree + field of study + start/end months + GPA if listed")
            lines.append("     - Do NOT drop bachelor's because a master's is present")
            lines.append("")
            lines.append("  3. skills[]: flat list, 15-30 entries when the resume supports it;")
            lines.append("     deduplicate but do not collapse categories")
            lines.append("")
            lines.append("  4. target_titles: AFTER parsing, GENERATE 10-15 job titles tailored")
            lines.append("     to THIS user's actual experience+skills+education. Bias toward IC")
            lines.append("     titles at the same seniority as their most recent role, plus one")
            lines.append("     step up. Not generic examples — titles they could realistically apply to.")
            lines.append("")
            lines.append("  5. answer_key_json: real professional prose for why_interested,")
            lines.append("     strengths, career_goals, cover_letter_template — referencing")
            lines.append("     specific achievements from the parsed work_experience.")
            lines.append("")
            lines.append("  Then PUT the extracted data to the cloud in a single call:")
            lines.append("    curl -sS -X PUT 'https://applyloop.vercel.app/api/settings/profile' \\")
            lines.append(f"         -H 'X-Worker-Token: {worker_token_hint}' \\")
            lines.append("         -H 'Content-Type: application/json' \\")
            lines.append("         -d '{\"work_experience\":[...], \"skills\":[...], \"education\":[...], \"answer_key_json\":{...}}'")
            lines.append("")
            lines.append("  Target titles go to preferences, not user_profiles:")
            lines.append("    curl -sS -X PUT 'https://applyloop.vercel.app/api/settings/preferences' \\")
            lines.append(f"         -H 'X-Worker-Token: {worker_token_hint}' \\")
            lines.append("         -H 'Content-Type: application/json' \\")
            lines.append("         -d '{\"target_titles\":[\"NLP Engineer\",\"LLM Engineer\",...]}'")
            lines.append("")
            lines.append("  On 200 OK, mirror to ./profile.json locally. Only AFTER the PUT")
            lines.append("  succeeds should you ask the user about anything the PDF didn't cover")
            lines.append("  (typically just the EEO fields).")
            lines.append("")

        if not is_complete:
            lines.append("PROFILE IS INCOMPLETE on the cloud source. Missing fields:")
            lines.append("  " + ", ".join(missing))
            lines.append("")
            lines.append("STEP 1 — collect each missing field by asking the user one at a time.")
            lines.append("  - skills[]: comma list of top 10-15 technical skills.")
            lines.append("  - school_name: university name only.")
            lines.append("  - graduation_year: 4-digit year.")
            lines.append("  - eeo.gender/race_ethnicity/veteran_status/disability_status: 'decline' is valid.")
            lines.append("  Do NOT re-ask for education_level/degree/field — already inferred from profile.education string.")
            lines.append("")
            lines.append("STEP 2 — persist every answer to the CLOUD FIRST (PUT), then mirror local:")
            lines.append("    curl -sS -X PUT 'https://applyloop.vercel.app/api/settings/profile' \\")
            lines.append(f"         -H 'X-Worker-Token: {worker_token_hint}' \\")
            lines.append("         -H 'Content-Type: application/json' \\")
            lines.append("         -d '{\"skills\": [\"Python\",\"PyTorch\"]}'")
            lines.append("  Accepted field names: work_experience, skills, education, education_level,")
            lines.append("  school_name, degree, graduation_year, gender, race_ethnicity,")
            lines.append("  veteran_status, disability_status, cover_letter_template, answer_key_json.")
            lines.append("  Only after the server returns 200, update ./profile.json to match.")
            lines.append("")
            lines.append("STEP 3 — once every missing field has a successful PUT, continue below.")
            lines.append("")
        else:
            lines.append("Profile is complete on the cloud. Skip straight to the announce + loop steps.")
            lines.append("")

        if tg_available:
            lines.append("STEP A — send a Telegram startup announcement now. Use curl:")
            lines.append(f"  curl -sS 'https://api.telegram.org/bot{tg_bot}/sendMessage' -d 'chat_id={tg_chat}' --data-urlencode 'text=[ApplyLoop] Session started for {first_name}. Targets: {target_titles}. Beginning scout loop now.'")
            lines.append("")
        else:
            lines.append("(Telegram bot not configured for this account — skip the Telegram step.)")
            lines.append("")

        lines.append("STEP B — greet the user in the terminal in ONE short line (first name only), then immediately")
        lines.append("begin the scout loop by running: cd ./packages/worker && python3 worker.py")
        lines.append("Do NOT wait for a 'start' or 'scout' command — this is an auto-run session. The user can")
        lines.append("type 'stop' at any time to halt the loop.")
        lines.append("")
        lines.append("If profile.json is missing entirely (not just incomplete), tell the user the install is")
        lines.append("broken and to run `applyloop update`. Otherwise proceed through the steps above in order.")

        return "\n".join(lines)

    @staticmethod
    def _ensure_claude_trust(cwd: str) -> None:
        """Pre-populate ~/.claude.json so Claude Code doesn't ask for
        workspace trust on first spawn. Schema observed from an existing
        install: {"projects": {"/abs/path": {"hasTrustDialogAccepted": true}}}.
        Merges into an existing file when present; creates the file otherwise.
        All errors swallowed — if this fails the user sees the prompt once,
        which is strictly better than failing to spawn Claude."""
        try:
            abs_cwd = os.path.abspath(cwd)
            config_path = os.path.expanduser("~/.claude.json")
            data: dict = {}
            if os.path.isfile(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        data = json.load(f) or {}
                except Exception:
                    data = {}
            projects = data.setdefault("projects", {})
            entry = projects.setdefault(abs_cwd, {})
            if entry.get("hasTrustDialogAccepted") is True:
                return
            entry["hasTrustDialogAccepted"] = True
            tmp_path = f"{config_path}.applyloop.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, config_path)
            logger.info(f"Pre-accepted Claude trust for {abs_cwd}")
        except Exception as e:
            logger.warning(f"Could not pre-accept Claude trust: {e}")

    def start(self) -> bool:
        """Spawn the PTY session."""
        if self.is_alive:
            return True

        claude = self._find_claude()
        if not claude:
            logger.error("Claude CLI not found")
            return False

        # Use the configured ApplyLoop workspace. (Legacy ~/.openclaw fallback
        # removed — honoring it broke multi-tenancy because every instance
        # would fight over the same directory regardless of APPLYLOOP_WORKSPACE.)
        # Prefer the install dir ($APPLYLOOP_HOME or ~/.applyloop) so relative
        # paths in AGENTS.md / SOUL.md resolve — that's where the script,
        # worker, profile.json, and .env all live. Fall back to WORKSPACE_DIR
        # and finally $HOME if the install dir doesn't exist.
        applyloop_home = os.environ.get(
            "APPLYLOOP_HOME", os.path.expanduser("~/.applyloop")
        )
        if os.path.isdir(applyloop_home):
            cwd = applyloop_home
        elif WORKSPACE_DIR.exists():
            cwd = str(WORKSPACE_DIR)
        else:
            try:
                WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
                cwd = str(WORKSPACE_DIR)
            except Exception:
                cwd = os.path.expanduser("~")

        # Belt-and-suspenders: make sure cwd actually exists on disk. If a
        # stale APPLYLOOP_HOME env var points at a deleted directory,
        # os.chdir() in the child would raise and claude would exit before
        # producing any output — the terminal tab would be empty with no
        # explanation. Create it if it's missing.
        try:
            os.makedirs(cwd, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create cwd {cwd}: {e}")
            cwd = os.path.expanduser("~")

        # Pre-accept Claude Code's workspace-trust dialog for this cwd so
        # the user isn't hit with "Is this a project you created or one you
        # trust?" on every fresh install. --dangerously-skip-permissions
        # bypasses tool-use prompts but NOT the one-time trust dialog;
        # that's stored in ~/.claude.json under projects[<cwd>].
        self._ensure_claude_trust(cwd)

        # Build the personalized initial prompt from profile.json + .env.
        # This is done in the parent (before fork) so we can log what we
        # detected and so the child doesn't need file-IO racing the exec.
        profile_snapshot = self._read_profile_snapshot(cwd)
        if not profile_snapshot["complete"]:
            logger.info(
                f"Profile incomplete — missing: {', '.join(profile_snapshot['missing'])}. "
                f"Claude will collect them interactively on first turn."
            )
        else:
            logger.info("Profile complete — Claude will auto-start scout loop + fire Telegram announce.")

        env = {**os.environ}
        token = load_token()
        if token:
            env["AUTOAPPLY_TOKEN"] = token
            env["WORKER_TOKEN"] = token

        # Build a PATH that includes every place claude/openclaw/npm could
        # live. When the app is launched from Finder/Dock, macOS gives the
        # process a bare PATH (/usr/bin:/bin:/usr/sbin:/sbin) and the
        # launcher's brew shellenv adds /opt/homebrew/bin, but if the user
        # bypasses the launcher (dev mode, launchctl, etc.) those dirs
        # aren't there. Explicitly prepend them so the child can always
        # find claude regardless of how the server was started.
        path_prepends = [
            os.path.expanduser("~/.local/bin"),
            "/opt/homebrew/bin",
            "/usr/local/bin",
        ]
        # Also include the npm global prefix if we can find it — that's
        # where `openclaw` lands.
        try:
            npm_prefix = os.environ.get("NPM_CONFIG_PREFIX") or (
                subprocess.run(
                    ["npm", "config", "get", "prefix"],
                    capture_output=True, text=True, timeout=3,
                ).stdout.strip() if shutil.which("npm") else ""
            )
            if npm_prefix and os.path.isdir(f"{npm_prefix}/bin"):
                path_prepends.append(f"{npm_prefix}/bin")
        except Exception:
            pass

        existing_path = env.get("PATH", "")
        existing_parts = existing_path.split(":") if existing_path else []
        for p in path_prepends:
            if p and p not in existing_parts:
                existing_parts.insert(0, p)
        env["PATH"] = ":".join(existing_parts)

        logger.info(
            f"PTY start: claude={claude} cwd={cwd} "
            f"PATH-head={':'.join(existing_parts[:3])}"
        )

        # Pre-fill the output buffer with a visible "starting..." line so
        # WebSocket clients that connect BEFORE Claude produces its first
        # byte see something instead of an empty black screen. The line
        # is sent via the normal _broadcast path the moment a subscriber
        # attaches.
        startup_banner = (
            "\x1b[36m[ApplyLoop]\x1b[0m Starting Claude Code session...\r\n"
            "\x1b[36m[ApplyLoop]\x1b[0m On first run, Claude will print an\r\n"
            "\x1b[36m[ApplyLoop]\x1b[0m OAuth URL - open it in your browser,\r\n"
            "\x1b[36m[ApplyLoop]\x1b[0m paste the code back here, and you're in.\r\n"
            "\r\n"
        ).encode("utf-8")
        self.output_buffer.append(startup_banner)

        # Build the shell wrapper command. On Unix: bash -c "wrapper_script".
        # On Windows: cmd /c "claude --dangerously-skip-permissions 'prompt'"
        initial_prompt = self._build_initial_prompt(cwd, profile_snapshot)
        env["APPLYLOOP_CLAUDE_BIN"] = claude

        if sys.platform == "win32":
            # Windows: ConPTY doesn't have fork semantics. The wrapper is
            # simpler — just run claude directly. Shell fallback on exit
            # goes to cmd.exe instead of zsh.
            escaped_prompt = initial_prompt.replace('"', '\\"')
            wrapper = (
                f'"{claude}" --dangerously-skip-permissions "{escaped_prompt}" '
                f'& echo. & echo [ApplyLoop] Claude exited. Type "claude" to restart. '
                f'& cmd /k'
            )
            spawn_cmd = ["cmd", "/c", wrapper]
        else:
            # Unix: bash wrapper with claude + zsh fallback (unchanged from
            # the pre-abstraction code — same shell script, just spawned
            # through the PTY backend instead of raw pty.fork).
            escaped_prompt = initial_prompt.replace("'", "'\"'\"'")
            wrapper_template = r"""#!/bin/bash
cd __CWD__
CYAN=$'\033[36m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
printf '%s[ApplyLoop]%s cwd=%s%s%s\r\n' "$CYAN" "$RESET" "$CYAN" "$PWD" "$RESET"
if [[ -d "$HOME/.claude" ]] && [[ -n "$(ls -A "$HOME/.claude" 2>/dev/null)" ]]; then
  printf '%s[ApplyLoop]%s Claude Code is authenticated - starting session...\r\n' "$GREEN" "$RESET"
  "$APPLYLOOP_CLAUDE_BIN" --dangerously-skip-permissions '__PROMPT__'
  CLAUDE_EXIT=$?
  CLAUDE_LOG_DIR="$HOME/.claude/logs"; LAST_LINES=""
  if [[ -d "$CLAUDE_LOG_DIR" ]]; then
    LATEST_LOG=$(ls -t "$CLAUDE_LOG_DIR"/*.log 2>/dev/null | head -1)
    [[ -n "$LATEST_LOG" && -f "$LATEST_LOG" ]] && LAST_LINES=$(tail -40 "$LATEST_LOG" 2>/dev/null)
  fi
  if echo "$LAST_LINES" | grep -qiE 'rate.?limit|429|too many requests'; then
    CLAUDE_REASON="API rate limit hit"; CLAUDE_HINT="Wait a few minutes."
  elif echo "$LAST_LINES" | grep -qiE 'daily.{0,20}limit|quota.{0,20}exceeded'; then
    CLAUDE_REASON="Daily quota used up"; CLAUDE_HINT="Resets at midnight Pacific."
  elif echo "$LAST_LINES" | grep -qiE 'invalid.{0,20}token|unauthorized|401'; then
    CLAUDE_REASON="Auth expired"; CLAUDE_HINT="Run: claude login"
  elif echo "$LAST_LINES" | grep -qiE 'connection.{0,20}refused|network|timeout'; then
    CLAUDE_REASON="Network error"; CLAUDE_HINT="Check internet connection."
  elif [[ "$CLAUDE_EXIT" == "0" ]]; then
    CLAUDE_REASON="Session ended normally"; CLAUDE_HINT="Type 'claude' to restart."
  else
    CLAUDE_REASON="Session ended (exit $CLAUDE_EXIT)"; CLAUDE_HINT="Type 'claude' to restart."
  fi
  printf '\r\n%s[ApplyLoop]%s %s%s\r\n' "$YELLOW" "$RESET" "$CLAUDE_REASON" "$RESET"
  printf '%s[ApplyLoop]%s %s\r\n' "$YELLOW" "$RESET" "$CLAUDE_HINT"
else
  printf '%s[ApplyLoop]%s Claude not authenticated. Run: %sclaude login%s\r\n\r\n' "$YELLOW" "$RESET" "$CYAN" "$RESET"
fi
exec /bin/zsh -l
"""
            wrapper = wrapper_template.replace("__CWD__", shlex.quote(cwd)).replace("__PROMPT__", escaped_prompt)
            spawn_cmd = ["/bin/bash", "-c", wrapper]

        # Spawn via the platform PTY backend
        self._pty = PlatformPTY()
        try:
            child_pid = self._pty.spawn(spawn_cmd, cwd=cwd, env=env)
        except Exception as e:
            logger.error(f"PTY spawn failed: {e}")
            self.output_buffer.append(
                f"\x1b[31m[ApplyLoop]\x1b[0m PTY spawn failed: {e}\r\n".encode()
            )
            return False

        # Parent process
        self.master_fd = getattr(self._pty, '_master_fd', None)  # Unix compat
        self.child_pid = child_pid
        self._alive = True
        self.started_at = time.time()
        self.last_output_at = time.time()
        self._current_record = SessionRecord(child_pid)
        self.session_id = self._current_record.session_id

        # Set terminal size (80x24 default, will be resized by client)
        self._pty.resize(80, 24)

        # Brief post-spawn death check
        exit_code = self._pty.wait_brief_death_check()
        if exit_code is not None:
            logger.error(
                f"PTY child died immediately after spawn "
                f"(pid={child_pid}, exit_code={exit_code}). "
                f"Likely causes: claude binary at {claude} is broken, "
                f"cwd {cwd} inaccessible, or exec environment missing "
                f"critical vars."
            )
            self.output_buffer.append(
                f"\x1b[31m[ApplyLoop]\x1b[0m Claude Code failed to start "
                f"(exit {exit_code}).\r\n"
                f"\x1b[31m[ApplyLoop]\x1b[0m Check ~/.autoapply/desktop.log "
                f"for details. Try: applyloop update\r\n\r\n".encode()
            )
            self._alive = False
            self.child_pid = None
            self._pty.close()
            self._pty = None
            return False

            # Start reading + watchdog in background. The watchdog detects
            # real apply-loop drift (not just PTY byte-flow idle) and fires
            # a tenant-scoped nudge with the next required action.
            self._read_task = asyncio.create_task(self._read_loop())
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())

            logger.info(f"PTY session started: PID {child_pid}, claude at {claude}")

            # Persist a session-boundary row to chat_log so the chat UI
            # renders a visible "── New session ──" divider between this
            # spawn and any previous one. Best-effort — never blocks
            # session start on a DB write error.
            try:
                from . import chat_log
                chat_log.append_session_boundary(
                    session_id=self.session_id or "unknown",
                    pid=child_pid,
                    cwd=cwd,
                )
            except Exception as _e:
                logger.debug(f"session boundary write skipped: {_e}")

            return True

    def _set_size(self, cols: int, rows: int):
        """Resize the PTY via the platform backend."""
        if self._pty is not None:
            self._pty.resize(cols, rows)

    async def _read_loop(self):
        """Read PTY output and broadcast to subscribers.
        Uses the platform PTY backend — works on both Unix and Windows."""
        loop = asyncio.get_event_loop()
        try:
            while self.is_alive and self._pty is not None:
                try:
                    data = await loop.run_in_executor(
                        None, lambda: self._pty.read(4096)
                    )
                    if not data:
                        break
                    self.output_buffer.append(data)
                    self.last_output_at = time.time()
                    self._broadcast(data)
                except (OSError, EOFError):
                    break
        finally:
            self._alive = False
            self._broadcast(b"\r\n[Session ended]\r\n")

    # ── Mission-driven watchdog + heartbeat ─────────────────────────────

    def _refresh_tenant_context(self) -> None:
        """Pull the tenant snapshot from the profile.json cache and Supabase
        sync state. Best-effort — if this fails, the loops fall back to a
        generic "finish setup" message. Called lazily from each loop tick
        rather than once at startup so tenant changes (e.g. new target_titles
        saved on the web dashboard) propagate without a restart.
        """
        import json
        import os as _os
        try:
            profile_path = _os.path.expanduser("~/.applyloop/profile.json")
            with open(profile_path) as f:
                data = json.load(f)
            prefs = (data.get("preferences") or {})
            self._tenant_snapshot = {
                "user_id": data.get("user_id") or data.get("id") or "unknown",
                "name": data.get("full_name") or data.get("name") or "the user",
                "email": data.get("email", ""),
                "target_titles": prefs.get("target_titles") or [],
                "preferred_locations": prefs.get("preferred_locations") or [],
                "daily_apply_limit": data.get("daily_apply_limit") or prefs.get("max_daily") or 25,
            }
        except Exception as e:
            logger.debug(f"refresh tenant context failed: {e}")

    def _read_mission_stats(self) -> dict:
        """Snapshot the current mission state from local_data + filesystem."""
        from . import local_data
        try:
            stats = local_data.get_stats() or {}
        except Exception:
            stats = {}
        try:
            worker_alive = local_data.is_worker_alive()
        except Exception:
            worker_alive = False
        try:
            scout_age = local_data.get_scout_age_minutes()
        except Exception:
            scout_age = None
        return {
            "applied_today": int(stats.get("applied_today", 0) or 0),
            "in_queue": int(stats.get("in_queue", 0) or 0),
            "total_applied": int(stats.get("total_applied", 0) or 0),
            "worker_alive": bool(worker_alive),
            "scout_age_min": scout_age,
            "idle_min": int((time.time() - self.last_output_at) / 60) if self.last_output_at else 0,
        }

    def _build_mission_heartbeat(self) -> str:
        """15-minute informational context refresh. Not a nudge — just keeps
        the mission fresh in Claude's working memory. Tenant-scoped so it
        always says WHO Claude is applying for."""
        snap = self._tenant_snapshot or {}
        stats = self._read_mission_stats()
        name = snap.get("name", "the user")
        targets = ", ".join(snap.get("target_titles", [])[:5]) or "(no target roles set)"
        locs = ", ".join(snap.get("preferred_locations", [])[:3]) or "any"
        worker_state = "alive" if stats["worker_alive"] else "NOT RUNNING"
        scout_age = (
            f"{stats['scout_age_min']:.0f}m ago"
            if stats["scout_age_min"] is not None
            else "never"
        )
        return (
            f"Mission context refresh (auto-heartbeat).\n"
            f"- Applying for: {name}\n"
            f"- Target roles: {targets}\n"
            f"- Locations: {locs}\n"
            f"- Queue: {stats['in_queue']} waiting, {stats['applied_today']} applied today "
            f"(cap {snap.get('daily_apply_limit', 25)})\n"
            f"- Last scout: {scout_age}\n"
            f"- Worker: {worker_state}\n"
            f"You don't need to respond. Just keep the mission in mind: "
            f"scout → filter → apply, 24/7, for THIS tenant's target roles. "
            f"If the worker isn't running, start it. If the queue is growing but "
            f"applied_today isn't moving, claim and apply the next job."
        )

    def _build_mission_nudge(self, drift: list[str]) -> str:
        """Mission-stall nudge. Fires when watchdog detects real progress
        drift — flat applied count, overdue scout, dead worker, or PTY idle.
        Body is tenant-scoped and names the required next action explicitly.
        Claude is told to ACT, not acknowledge."""
        snap = self._tenant_snapshot or {}
        stats = self._read_mission_stats()
        name = snap.get("name", "the user")
        user_id = (snap.get("user_id") or "unknown")[:8]
        targets = ", ".join(snap.get("target_titles", [])[:5]) or "(not set)"
        locs = ", ".join(snap.get("preferred_locations", [])[:3]) or "any"
        drift_str = "; ".join(drift) if drift else "no specific signal"
        scout_desc = (
            f"{stats['scout_age_min']:.0f}m ago"
            if stats['scout_age_min'] is not None
            else "never"
        )
        return (
            f"Mission stall detected (auto-nudge).\n"
            f"Tenant: {name} ({user_id})\n"
            f"Target roles: {targets}\n"
            f"Preferred locations: {locs}\n"
            f"State:\n"
            f"  - Queue: {stats['in_queue']} waiting\n"
            f"  - Applied today: {stats['applied_today']} / {snap.get('daily_apply_limit', 25)}\n"
            f"  - Worker alive: {stats['worker_alive']}\n"
            f"  - PTY idle: {stats['idle_min']}m\n"
            f"  - Last scout: {scout_desc}\n"
            f"Drift signals: {drift_str}\n\n"
            f"Your ultimate mission: keep scout → filter → apply running 24/7 "
            f"for THIS tenant's profile. You are NOT making progress.\n\n"
            f"Required next action (pick the first that applies):\n"
            f"  1. Worker not running? → cd ~/.applyloop/packages/worker && python3 worker.py\n"
            f"  2. Queue has jobs but apply loop stalled? → check worker logs, "
            f"kill stuck processes, restart worker\n"
            f"  3. Scout overdue? → worker's scout thread ticks every 30m. "
            f"If it isn't, the worker process is dead — restart it.\n"
            f"  4. All look fine? → claim the next queued row and apply to it.\n\n"
            f"Do not just acknowledge this. Take the action. Report back when "
            f"applied_today changes."
        )

    def _submit_to_pty(self, body: str) -> None:
        """Write a normal message to the terminal and press Enter.

        No /btw — this is a real message that Claude MUST act on.

        Rules for Claude Code's raw-mode TUI:
          - NO \\n (0x0a) — that's cursor movement, not submit. Corrupts input.
          - End with \\r (0x0d) — that's Enter. Actually submits the message.

        Body is collapsed into one line (newlines → spaces), then \\r appended.
        """
        flat = body.replace("\r\n", " ").replace("\n", " ").replace("\r", "")
        while "  " in flat:
            flat = flat.replace("  ", " ")
        flat = flat.strip()
        if not flat:
            return
        self.write(f"{flat}\r".encode("utf-8"))

    def _nudge_cooldown_ok(self) -> bool:
        """Rate-limit nudges to at most once per NUDGE_COOLDOWN seconds so
        Claude has time to actually ACT on a nudge before getting another."""
        return (time.time() - self._last_nudge_at) >= self.NUDGE_COOLDOWN

    async def _mission_heartbeat_loop(self):
        """Informational status refresh every 15 min. Always fires while
        the session is alive; not rate-limited (heartbeats are context, not
        actions). Tenant snapshot is re-read each tick so changes to the
        web dashboard propagate without a PTY restart."""
        try:
            while self.is_alive:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                if not self.is_alive:
                    return
                self._refresh_tenant_context()
                body = self._build_mission_heartbeat()
                logger.info("Mission heartbeat → PTY")
                self._submit_to_pty(body)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Heartbeat loop ended: {e}")

    async def _watchdog_loop(self):
        """Mission-drift guard. Ticks every 5 min and fires a nudge when any
        of four drift signals trip:
          1. applied_today hasn't grown in STUCK_APPLIED_CYCLES ticks AND
             queue has jobs (worker alive but apply gate stuck)
          2. scout is overdue by 2x SCOUT_INTERVAL_MINUTES (30m → 60m)
          3. worker process dead (worker.pid points nowhere)
          4. PTY idle for IDLE_THRESHOLD (fallback — PTY-byte-flow check)

        Cooldown: at most one nudge per NUDGE_COOLDOWN seconds, no matter
        how many signals fire, so Claude gets time to act between pokes.
        """
        # Import here to keep top-level import clean + avoid circular with
        # config on restart.
        try:
            from config import SCOUT_INTERVAL_MINUTES  # noqa: F401 — sanity check
            scout_interval_min = 30
            try:
                from config import SCOUT_INTERVAL_MINUTES as _siv
                scout_interval_min = int(_siv)
            except Exception:
                pass
        except Exception:
            scout_interval_min = 30

        scout_stale_min = scout_interval_min * self.SCOUT_STALE_MULTIPLIER

        try:
            while self.is_alive:
                await asyncio.sleep(self.WATCHDOG_INTERVAL)
                if not self.is_alive:
                    return

                self._refresh_tenant_context()
                stats = self._read_mission_stats()
                drift: list[str] = []

                # Signal 1 — applied_today flat with non-empty queue
                if (
                    self._last_applied_count is not None
                    and stats["applied_today"] == self._last_applied_count
                    and stats["in_queue"] > 0
                ):
                    self._stuck_cycles += 1
                else:
                    self._stuck_cycles = 0
                self._last_applied_count = stats["applied_today"]
                if self._stuck_cycles >= self.STUCK_APPLIED_CYCLES:
                    drift.append(
                        f"applied_today stuck at {stats['applied_today']} for "
                        f"{self._stuck_cycles * (self.WATCHDOG_INTERVAL // 60)}m "
                        f"with {stats['in_queue']} in queue"
                    )

                # Signal 2 — scout overdue
                if stats["scout_age_min"] is not None and stats["scout_age_min"] > scout_stale_min:
                    drift.append(
                        f"scout overdue by {stats['scout_age_min'] - scout_interval_min:.0f}m"
                    )
                elif stats["scout_age_min"] is None and stats["worker_alive"]:
                    # Worker process alive but has never touched scout.ts —
                    # shouldn't happen but worth surfacing.
                    drift.append("scout heartbeat file missing despite worker alive")

                # Signal 3 — worker process dead
                if not stats["worker_alive"]:
                    drift.append("worker process not running")

                # Signal 4 — PTY silence fallback
                if stats["idle_min"] >= (self.IDLE_THRESHOLD // 60):
                    drift.append(f"PTY idle for {stats['idle_min']}m")

                if drift and self._nudge_cooldown_ok():
                    logger.info(f"Mission drift → nudge: {drift}")
                    body = self._build_mission_nudge(drift)
                    self._submit_to_pty(body)
                    self._last_nudge_at = time.time()
                    # Reset stuck counter after firing so we don't instantly
                    # re-trip on the next tick.
                    self._stuck_cycles = 0
                elif drift:
                    logger.debug(f"Drift detected but on cooldown: {drift}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Watchdog ended: {e}")

    def _broadcast(self, data: bytes):
        """Send data to all WebSocket subscribers."""
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._subscribers:
            self._subscribers.remove(q)

    def write(self, data: bytes):
        """Write user input to the PTY via the platform backend."""
        if self._pty is not None and self.is_alive:
            self._pty.write(data)

    def resize(self, cols: int, rows: int):
        """Handle terminal resize from the client."""
        self._set_size(cols, rows)

    def stop(self):
        """Kill the PTY session via the platform backend."""
        if hasattr(self, '_current_record') and self._current_record:
            self._current_record.stop()
        if self._pty is not None:
            try:
                self._pty.terminate()
            except Exception:
                pass
            try:
                self._pty.close()
            except Exception:
                pass
            self._pty = None
        self.master_fd = None
        self.child_pid = None
        self._alive = False
        if self._read_task:
            self._read_task.cancel()
            self._read_task = None
        if self._watchdog_task:
            self._watchdog_task.cancel()
            self._watchdog_task = None

    def restart(self):
        """Stop and restart."""
        self.stop()
        self.output_buffer.clear()
        self.start()


# ── Session Manager ──────────────────────────────────────────────────────────

class SessionManager:
    """
    Manages PTY sessions — one active at a time, with history.

    Rules:
    - Only ONE session can be active at a time
    - Dead sessions stay in history (viewable, deletable, not resumable)
    - Deleting the active session stops it and does NOT auto-create a new one
    - User must click "New Session" or "Start Session" to create a new one
    - No duplicates in the session list
    """

    def __init__(self):
        self.sessions: list[SessionRecord] = []
        self.pty: PTYSession = PTYSession()

    @property
    def active_session_id(self) -> str | None:
        return self.pty.session_id if self.pty.is_alive else None

    def _sync(self):
        """Ensure session list is consistent with PTY state."""
        # Mark records as stopped if their PTY is dead
        active_id = self.active_session_id
        for s in self.sessions:
            if s.status == "running" and s.session_id != active_id:
                s.stop()
        # Deduplicate by session_id
        seen = set()
        unique = []
        for s in self.sessions:
            if s.session_id not in seen:
                seen.add(s.session_id)
                unique.append(s)
        self.sessions = unique

    def get_sessions(self) -> list[dict]:
        self._sync()
        return [s.to_dict() for s in self.sessions]

    def new_session(self) -> dict:
        """Stop current PTY, create a fresh one."""
        if self.pty.is_alive:
            self.pty.stop()
        self.pty = PTYSession()
        self.pty.start()
        # Register in history (only if start succeeded)
        if self.pty._current_record:
            self.sessions.append(self.pty._current_record)
        self._sync()
        return self.pty.status()

    def delete_session(self, session_id: str) -> dict:
        """Delete a session. If active, just stops it — does NOT auto-create."""
        self._sync()
        record = next((s for s in self.sessions if s.session_id == session_id), None)
        if not record:
            return {"ok": False, "error": "Session not found"}

        is_active = (self.pty.session_id == session_id)
        if is_active and self.pty.is_alive:
            self.pty.stop()

        self.sessions.remove(record)
        return {"ok": True, "active_session_id": self.active_session_id}

    def clear_history(self):
        """Remove all stopped sessions from history."""
        self._sync()
        self.sessions = [s for s in self.sessions if s.status == "running"]


session_manager = SessionManager()


async def pty_terminal_websocket(ws: WebSocket):
    """
    Interactive PTY terminal over WebSocket.

    Messages from client:
      - {"type": "input", "data": "..."} — keystrokes
      - {"type": "resize", "cols": N, "rows": N} — terminal resize
      - {"type": "start"} — start/restart session

    Messages to client:
      - binary frames — raw PTY output
    """
    await ws.accept()

    # Auto-start if not running (go through manager so it's registered)
    if not session_manager.pty.is_alive:
        session_manager.new_session()

    # Send status
    await ws.send_json({"type": "status", **session_manager.pty.status()})

    # Backfill — send buffered output
    for chunk in session_manager.pty.output_buffer:
        await ws.send_bytes(chunk)

    # Subscribe to live output
    queue = session_manager.pty.subscribe()

    async def _relay_output():
        """Forward PTY output to WebSocket."""
        try:
            while True:
                data = await queue.get()
                await ws.send_bytes(data)
        except Exception:
            pass

    relay_task = asyncio.create_task(_relay_output())

    try:
        while True:
            msg = await ws.receive()

            if "text" in msg:
                import json
                parsed = json.loads(msg["text"])
                msg_type = parsed.get("type", "")

                if msg_type == "input":
                    session_manager.pty.write(parsed["data"].encode("utf-8"))
                elif msg_type == "resize":
                    session_manager.pty.resize(parsed.get("cols", 80), parsed.get("rows", 24))
                elif msg_type == "start":
                    session_manager.pty.restart()
                    await ws.send_json({"type": "status", **session_manager.pty.status()})
                elif msg_type == "stop":
                    session_manager.pty.stop()
                    await ws.send_json({"type": "status", **session_manager.pty.status()})

            elif "bytes" in msg:
                # Raw binary input from xterm.js
                session_manager.pty.write(msg["bytes"])

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"PTY WS closed: {e}")
    finally:
        relay_task.cancel()
        session_manager.pty.unsubscribe(queue)
