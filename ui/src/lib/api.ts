const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8723/api";

// ── Types ──────────────────────────────────────────────

export interface Session {
  id: string;
  summary: string;
  project_path: string;
  message_count: number;
  first_message_at: string;
  last_message_at: string;
}

export interface ContentBlock {
  block_type: "text" | "thinking" | "tool_use" | "tool_result";
  text?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
}

export interface Event {
  event_id: string;
  session_id: string;
  timestamp: string;
  role: string;
  content_blocks: ContentBlock[];
  token_input: number;
  token_output: number;
  cwd?: string;
  git_branch?: string;
  model?: string;
  content_text?: string;
  snippet?: string;
}

export interface Stats {
  total_sessions: number;
  total_events: number;
  user_events: number;
  assistant_events: number;
  tool_uses: number;
  total_tokens: number;
  cache_hit_rate: number | null;
  per_model: { model: string; tokens: number; events: number }[];
  per_provider: { provider: string; tokens: number; events: number }[];
}

export interface DailyStat {
  date: string;
  count: number;
  tokens: number;
}

export interface Health {
  status: string;
  sessions_count: number;
  events_count: number;
  fts_enabled: boolean;
  version: string;
}

export interface PaginatedMeta {
  page: number;
  per_page: number;
  total: number;
  pages: number;
}

export interface PaginatedResponse<T> {
  data: T[];
  meta: PaginatedMeta;
}

// ── HTTP Client ────────────────────────────────────────

async function fetchApi<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
): Promise<T> {
  const url = new URL(`${API_BASE}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") {
        url.searchParams.set(k, String(v));
      }
    });
  }
  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

async function postApi<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// ── Endpoints ──────────────────────────────────────────

export function getHealth(): Promise<Health> {
  return fetchApi<Health>("/health");
}

export function getSessions(
  page = 1,
  perPage = 50,
  sort = "last_message_at",
  order = "desc",
  project?: string,
): Promise<PaginatedResponse<Session>> {
  return fetchApi<PaginatedResponse<Session>>("/sessions", {
    page,
    per_page: perPage,
    sort,
    order,
    project,
  });
}

export function getSession(id: string): Promise<Session> {
  return fetchApi<Session>(`/sessions/${id}`);
}

export function getSessionEvents(
  id: string,
): Promise<{ data: Event[]; meta: { total: number } }> {
  return fetchApi<{ data: Event[]; meta: { total: number } }>(
    `/sessions/${id}/events`,
  );
}

export interface TreeNode {
  event_id: string;
  role: string;
  timestamp: string;
  depth: number;
  children: TreeNode[];
}

export function getSessionTree(
  id: string,
): Promise<{ data: TreeNode[] }> {
  return fetchApi<{ data: TreeNode[] }>(`/sessions/${id}/tree`);
}

export function search(
  query: string,
  page = 1,
  perPage = 20,
): Promise<PaginatedResponse<Event>> {
  return fetchApi<PaginatedResponse<Event>>("/search", {
    q: query,
    page,
    per_page: perPage,
  });
}

export function getStats(): Promise<Stats> {
  return fetchApi<Stats>("/stats");
}

export function getDailyStats(days = 30): Promise<{ data: DailyStat[] }> {
  return fetchApi<{ data: DailyStat[] }>("/stats/daily", { days });
}

export interface ToolUsage {
  tool_name: string;
  count: number;
}

export function getToolUsageStats(
  limit = 15,
): Promise<{ data: ToolUsage[] }> {
  return fetchApi<{ data: ToolUsage[] }>("/stats/tools", { limit });
}

// ── Sync (scan) ────────────────────────────────────────

export function triggerScan(): Promise<{ status: string; sessions: number; events: number; skipped: number }> {
  return postApi<{ status: string; sessions: number; events: number; skipped: number }>("/scan");
}

export function triggerFullScan(): Promise<{ status: string; sessions: number; events: number; skipped: number }> {
  return postApi<{ status: string; sessions: number; events: number; skipped: number }>("/scan/full");
}
