"""ApplyLoop Claude-Agent-SDK brain package.

The brain is one long-running Claude session with tool access to the
browser (OpenClaw), the job queue (Supabase + local SQLite), tenant
profiles, scout sources, and Telegram notifications. It replaces the
stateless `claude --print` subprocesses that `applier/llm_fill.py` used
to spawn per form. See packages/worker/brain/main.py for the entry.
"""
