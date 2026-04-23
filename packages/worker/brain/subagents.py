"""Subagent definitions for the ApplyLoop brain.

The SDK's `ClaudeAgentOptions.agents` takes a dict of
`AgentDefinition`s. Each subagent runs in its own conversation context;
only its final message returns to the parent brain. This keeps a noisy
scout cycle from polluting the apply session's context and vice-versa.

Only the parent brain has to know the high-level loop. Subagents know
one job each and delegate everything via the shared MCP tool server.
"""
from __future__ import annotations

from claude_agent_sdk import AgentDefinition

from brain.tools import allowed_tool_names


def _all_tools() -> list[str]:
    return allowed_tool_names()


SCOUT_AGENT = AgentDefinition(
    description=(
        "Run ONE scout cycle for the current tenant. Call scout_list_sources to see what's available, pick an order (prefer deterministic ATS sources like greenhouse/ashby/lever first; LinkedIn last because it's browser-heavy). For each source, call scout_run_source and inspect the JobPost list it returns. Send notify_heartbeat updates along the way. When done, summarize total jobs found across sources and return."
    ),
    prompt=(
        "You are the scout subagent. One cycle, then return. Be mechanical: you do not filter jobs here — that happens in the enqueue path. Just run the sources the parent told you to run and report what you found. If a source errors, log it via notify_heartbeat and continue. Do not apply to any job."
    ),
    tools=_all_tools(),
    model="sonnet",
)


APPLY_AGENT = AgentDefinition(
    description=(
        "Apply to ONE job end-to-end. Call queue_claim_next. Read knowledge_get_ats_playbook for the job's ATS. Drive the browser: navigate, snapshot, fill, submit. Between every submit, call browser_dismiss_stray_tabs with the apply hostname. Positive-confirmation ONLY — look for thank-you text before logging submitted. Always log an outcome (success or failure) via queue_log_application + queue_update_status + notify_telegram before returning."
    ),
    prompt=(
        "You are the apply subagent. One job, then return. You MUST complete the outcome triple (log_application + update_status + telegram) before returning — even on failure. Use tenant_load + knowledge_get_ats_playbook up front so you know the profile values and the ATS quirks. If the first snapshot shows a LinkedIn sign-in wall, do not try to sign in — instead Google the company + role and navigate to the first ATS result."
    ),
    tools=_all_tools(),
    model="sonnet",
)


AGENTS = {
    "scout-agent": SCOUT_AGENT,
    "apply-agent": APPLY_AGENT,
}
