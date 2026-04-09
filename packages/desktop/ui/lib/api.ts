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
