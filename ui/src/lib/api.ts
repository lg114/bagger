const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8723/api";
const API_TOKEN = import.meta.env.VITE_API_TOKEN;

// ── Types ──────────────────────────────────────────────

export interface Session {
  id: string;
  summary: string;
  project_path: string;
  message_count: number;
  first_message_at: string;
  last_message_at: string;
  source?: string;
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
  source?: string;
}

export interface Stats {
  total_sessions: number;
  total_events: number;
  user_events: number;
  assistant_events: number;
  tool_uses: number;
  total_tokens: number;
  total_cost_usd: number;
  cache_hit_rate: number | null;
  per_model: { model: string; tokens: number; events: number; cost: number }[];
  per_provider: { provider: string; tokens: number; events: number; cost: number }[];
}

export interface DailyStat {
  date: string;
  count: number;
  tokens: number;
  cost: number;
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
  const res = API_TOKEN
    ? await fetch(url.toString(), {
        headers: { Authorization: `Bearer ${API_TOKEN}` },
      })
    : await fetch(url.toString());
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

async function postApi<T>(path: string): Promise<T> {
  const res = API_TOKEN
    ? await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${API_TOKEN}` },
      })
    : await fetch(`${API_BASE}${path}`, { method: "POST" });
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
  source?: string,
): Promise<PaginatedResponse<Session>> {
  return fetchApi<PaginatedResponse<Session>>("/sessions", {
    page,
    per_page: perPage,
    sort,
    order,
    project,
    source,
  });
}

export function getSession(id: string, source?: string): Promise<Session> {
  const qs = source ? `?source=${encodeURIComponent(source)}` : "";
  return fetchApi<Session>(`/sessions/${id}${qs}`);
}

/** Canonical list of every distinct source in the store (the source facet). */
export function getSources(project?: string): Promise<string[]> {
  const qs = project ? `?project=${encodeURIComponent(project)}` : "";
  return fetchApi<{ sources: string[] }>(`/sources${qs}`).then((r) => r.sources);
}

export function getSessionEvents(
  id: string,
  source?: string,
  page = 1,
  perPage = 50,
): Promise<PaginatedResponse<Event>> {
  const params: Record<string, string | number | undefined> = {
    page,
    per_page: perPage,
  };
  if (source) params.source = source;
  return fetchApi<PaginatedResponse<Event>>(`/sessions/${id}/events`, params);
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
  source?: string,
): Promise<{ data: TreeNode[] }> {
  const qs = source ? `?source=${encodeURIComponent(source)}` : "";
  return fetchApi<{ data: TreeNode[] }>(`/sessions/${id}/tree${qs}`);
}

export function search(
  query: string,
  page = 1,
  perPage = 20,
  source?: string,
): Promise<PaginatedResponse<Event>> {
  return fetchApi<PaginatedResponse<Event>>("/search", {
    q: query,
    page,
    per_page: perPage,
    source,
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

// A scan runs in the background; the trigger returns immediately and the UI
// polls /scan/status until it completes (see ImportPage).
export function triggerScan(): Promise<{ status: string }> {
  return postApi<{ status: string }>("/scan");
}

export function triggerFullScan(): Promise<{ status: string }> {
  return postApi<{ status: string }>("/scan/full");
}

export interface ScanResult {
  sessions: number;
  events: number;
  skipped: number;
  errors?: number;
}

export interface ScanStatus {
  running: boolean;
  done: boolean;
  result: ScanResult | null;
  error: string | null;
}

export function getScanStatus(): Promise<ScanStatus> {
  return fetchApi<ScanStatus>("/scan/status");
}

// ── Export (session -> Markdown) ───────────────────────

/**
 * Trigger a Markdown download for a session.
 *
 * We point a real <a> at the export endpoint and click it synchronously
 * inside the click handler. The server responds with
 * `Content-Disposition: attachment`, so the browser downloads the file
 * natively — and the filename comes from that header.
 *
 * This is deliberately synchronous. The previous implementation did
 * `fetch` → `await` → build a blob → `a.click()`. Because the `click()`
 * happened after an `await`, the user-activation window had already expired
 * and Chrome silently dropped the download (no error thrown, nothing
 * downloaded). A synchronous anchor click keeps the download inside the
 * gesture, so it always works.
 */
export async function exportSessionMarkdown(
  id: string,
  format = "markdown",
  source?: string,
): Promise<void> {
  const params = new URLSearchParams({ format });
  if (source) params.set("source", source);
  const url = `${API_BASE}/sessions/${encodeURIComponent(id)}/export?${params.toString()}`;
  if (API_TOKEN) {
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${API_TOKEN}` },
    });
    if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = `bagger-${source ?? "session"}-${id.slice(0, 24)}.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objectUrl);
    return;
  }

  const a = document.createElement("a");
  a.href = url;
  a.download = `bagger-${source ?? "session"}-${id.slice(0, 24)}.md`;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
