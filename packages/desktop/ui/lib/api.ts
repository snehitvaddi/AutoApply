/**
 * API client for the FastAPI desktop backend.
 * Static export: calls go directly to the FastAPI server on the same origin.
 */

const API_BASE = "/api";

async function apiFetch<T = unknown>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...opts?.headers },
    ...opts,
  });
  if (!res.ok) throw new Error(`API ${path}: ${res.status}`);
  return res.json();
}

// ── Auth ────────────────────────────────────────────────────────────────────

export async function checkAuth() {
  return apiFetch<{ authenticated: boolean; profile?: Record<string, unknown> }>("/auth/status");
}

export async function saveToken(token: string) {
  return apiFetch("/auth/token", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

// ── Worker Control ──────────────────────────────────────────────────────────

export async function getWorkerStatus() {
  return apiFetch<{
    running: boolean;
    pid: number | null;
    uptime: number;
    restart_count: number;
    buffer_lines: number;
  }>("/worker/status");
}

export async function startWorker() {
  return apiFetch("/worker/start", { method: "POST" });
}

export async function stopWorker() {
  return apiFetch("/worker/stop", { method: "POST" });
}

export async function restartWorker() {
  return apiFetch("/worker/restart", { method: "POST" });
}

// ── Stats ───────────────────────────────────────────────────────────────────

export interface DashboardStats {
  applied_today: number;
  total_applied: number;
  in_queue: number;
  success_rate: number;
}

export async function getStats() {
  return apiFetch<{ ok: boolean; data: DashboardStats }>("/stats");
}

export async function getDailyBreakdown() {
  return apiFetch<{ ok: boolean; data: { date: string; submitted: number; failed: number }[] }>(
    "/stats/daily"
  );
}

export async function getPlatformBreakdown() {
  return apiFetch<{ ok: boolean; data: { name: string; value: number }[] }>("/stats/platforms");
}

// ── Pipeline ────────────────────────────────────────────────────────────────

export interface PipelineJob {
  id: string;
  company: string;
  title: string;
  ats: string;
  posted_at: string;
  status: string;
  error?: string;
  url?: string;
  location?: string;
  scouted_at?: string;
  applied_at?: string;
  updated_at?: string;
  screenshot?: string;
}

export interface CurrentlyApplyingJob {
  id: number;
  company: string;
  title: string;
  url: string;
  ats: string;
  location: string;
  updated_at: string;
}

export interface PipelineData {
  discovered: PipelineJob[];
  queued: PipelineJob[];
  applying: PipelineJob[];
  submitted: PipelineJob[];
  failed: PipelineJob[];
}

export async function getPipeline() {
  return apiFetch<{ ok: boolean; data: PipelineData }>("/pipeline");
}

export async function getCurrentlyApplying() {
  return apiFetch<{ ok: boolean; data: CurrentlyApplyingJob | null }>("/pipeline/current");
}

export async function getStuckJobs() {
  return apiFetch<{ ok: boolean; data: PipelineJob[] }>("/pipeline/stuck");
}

export async function resetStuckJobs() {
  return apiFetch<{ ok: boolean; reset: number }>("/pipeline/reset-stuck", { method: "POST" });
}

export async function focusBrowser() {
  return apiFetch<{ ok: boolean; focused?: string; error?: string }>("/browser/focus", {
    method: "POST",
  });
}

// ── First-run setup ────────────────────────────────────────────────────────

export interface PreflightCheck {
  id:
    | "token"
    | "profile"
    | "resume"
    | "preferences"
    | "claude_cli"
    | "openclaw_cli"
    | "openclaw_gateway"
    | "git";
  ok: boolean;
  label: string;
  detail: string;
  remediation?: {
    type: "route" | "install" | "link";
    target: string;
    command?: string;
    fallback_url?: string;
  };
  optional?: boolean;
}

export interface SetupStatus {
  setup_complete: boolean;
  reason?: "no_token" | "token_invalid" | "offline" | "token_revoked" | string;
  detail?: string;
  needs?: string[];
  checks?: PreflightCheck[];
}

export interface InstallProgress {
  ok: boolean;
  running: boolean;
  exit_code: number | null;
  last_lines: string[];
  started: boolean;
  log_path?: string;
}

export async function installTool(
  tool: "claude" | "openclaw" | "git" | "brew"
) {
  return apiFetch<{
    ok: boolean;
    error?: string;
    pid?: number;
    log_path?: string;
    needs_brew?: boolean;
    needs_node?: boolean;
    already_running?: boolean;
  }>("/setup/install-tool", {
    method: "POST",
    body: JSON.stringify({ tool }),
  });
}

export async function getInstallProgress(tool: string) {
  return apiFetch<InstallProgress>(
    `/setup/install-progress?tool=${encodeURIComponent(tool)}`
  );
}

export interface AuthState {
  status: "ok" | "revoked" | "unknown" | "no_token";
  last_checked?: number;
  last_error?: string | null;
}

export async function getAuthState() {
  return apiFetch<AuthState>("/auth/state");
}

export async function clearReauthMarker() {
  return apiFetch<{ ok: boolean }>("/setup/clear-reauth", { method: "POST" });
}

export interface ActivateResult {
  ok: boolean;
  user?: {
    email?: string | null;
    name?: string | null;
    tier?: string | null;
  };
  resume_downloaded?: boolean;
  error?: string;
  suggestion?: string;
  message?: string;
}

export async function getSetupStatus() {
  return apiFetch<SetupStatus>("/setup/status");
}

export async function activateWithCode(code: string) {
  return apiFetch<ActivateResult>("/setup/activate", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}

// ── Queue Management ────────────────────────────────────────────────────────

export async function deleteFromQueue(jobId: number) {
  return apiFetch<{ ok: boolean; error?: string }>(`/queue/${jobId}`, {
    method: "DELETE",
  });
}

export async function clearQueue() {
  return apiFetch<{ ok: boolean; deleted: number }>("/queue", {
    method: "DELETE",
  });
}

// ── Applications ────────────────────────────────────────────────────────────

export interface Application {
  id?: number;
  company: string;
  title: string;
  ats: string;
  status: string;
  applied_at: string;
  error?: string;
}

export async function getRecentApplications(limit = 20) {
  return apiFetch<{ ok: boolean; data: Application[] }>(`/applications/recent?limit=${limit}`);
}

// ── Profile & Preferences ───────────────────────────────────────────────────

export async function getProfile() {
  return apiFetch<{ ok: boolean; data: Record<string, unknown> }>("/profile");
}

export async function updateProfile(data: Record<string, unknown>) {
  return apiFetch("/profile", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function getPreferences() {
  return apiFetch<{ ok: boolean; data: Record<string, unknown> }>("/preferences");
}

export async function updatePreferences(data: Record<string, unknown>) {
  return apiFetch("/preferences", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

// ── Resumes ─────────────────────────────────────────────────────────────────

export interface ResumeRow {
  id: string;
  storage_path: string;
  file_name: string;
  is_default: boolean;
  target_keywords: string[];
  created_at: string;
}

export async function listResumes() {
  return apiFetch<{ ok: boolean; data: { resumes: ResumeRow[] } }>("/resumes");
}

export async function uploadResume(
  file: File,
  opts?: { isDefault?: boolean; targetKeywords?: string[] }
): Promise<{ ok: boolean; data?: { resume: ResumeRow; size_bytes: number }; error?: string }> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("is_default", String(opts?.isDefault !== false));
  fd.append("target_keywords", (opts?.targetKeywords || []).join(","));
  const res = await fetch(`${API_BASE}/resumes/upload`, {
    method: "POST",
    body: fd,
  });
  // Don't use apiFetch here — it forces application/json Content-Type,
  // which breaks multipart boundary detection.
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    return { ok: false, error: `HTTP ${res.status}: ${txt.slice(0, 200)}` };
  }
  return res.json();
}

// ── Session Control ─────────────────────────────────────────────────────────

export interface SessionStatus {
  alive: boolean;
  state: string;
  cli: string;
  uptime: number;
  buffer_lines: number;
  subscribers: number;
}

export async function getSessionStatus() {
  return apiFetch<SessionStatus>("/session/status");
}

export async function startSession() {
  return apiFetch("/session/start", { method: "POST" });
}

export async function stopSession() {
  return apiFetch("/session/stop", { method: "POST" });
}

export async function restartSession() {
  return apiFetch("/session/restart", { method: "POST" });
}

// ── Background Jobs ─────────────────────────────────────────────────────────

export interface BackgroundProcess {
  id: string;
  name: string;
  description: string;
  type: "process" | "session" | "cron";
  running: boolean;
  pid?: number;
  uptime?: number;
  state?: string;
  last_action?: string;
  details?: string;
  last_run?: string;
  interval?: string;
}

export async function getBackgroundJobs() {
  return apiFetch<{ ok: boolean; processes: BackgroundProcess[] }>("/jobs/background");
}

// ── PTY Sessions ────────────────────────────────────────────────────────────

export interface PTYSessionRecord {
  session_id: string;
  pid: number;
  started_at: number;
  stopped_at: number | null;
  status: "running" | "stopped";
  duration: number;
}

export async function getPTYSessions() {
  return apiFetch<{
    ok: boolean;
    active_session_id: string | null;
    current: Record<string, unknown>;
    history: PTYSessionRecord[];
    total: number;
  }>("/pty/sessions");
}

export async function createNewPTYSession() {
  return apiFetch("/pty/sessions/new", { method: "POST" });
}

export async function deletePTYSession(sessionId: string) {
  return apiFetch<{ ok: boolean; active_session_id: string }>(`/pty/sessions/${sessionId}`, {
    method: "DELETE",
  });
}
