import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  getHealth,
  getSessions,
  getSession,
  getSessionEvents,
  search,
  getStats,
  getDailyStats,
  getToolUsageStats,
  triggerScan,
  triggerFullScan,
} from "../api";

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  mockFetch.mockReset();
});

// ── Helpers ──────────────────────────────────────────────

function mockApiResponse(data: unknown, status = 200) {
  mockFetch.mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: async () => data,
  });
}

// ── getHealth ────────────────────────────────────────────

describe("getHealth", () => {
  it("returns health data on success", async () => {
    const health = { status: "ok", sessions_count: 5, events_count: 10, fts_enabled: true, version: "0.2.0" };
    mockApiResponse(health);

    const result = await getHealth();
    expect(result).toEqual(health);
    expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining("/health"));
  });

  it("throws on HTTP error", async () => {
    mockApiResponse({}, 500);
    await expect(getHealth()).rejects.toThrow("API error: 500");
  });
});

// ── getSessions ──────────────────────────────────────────

describe("getSessions", () => {
  it("returns paginated sessions with defaults", async () => {
    const data = { data: [{ id: "s1", summary: "Test" }], meta: { page: 1, per_page: 50, total: 1, pages: 1 } };
    mockApiResponse(data);

    const result = await getSessions();
    expect(result.data).toHaveLength(1);
    expect(result.data[0].id).toBe("s1");
  });

  it("passes page and sort params", async () => {
    mockApiResponse({ data: [], meta: { page: 2, per_page: 20, total: 0, pages: 0 } });

    await getSessions(2, 20, "first_message_at", "asc");
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("page=2");
    expect(url).toContain("per_page=20");
    expect(url).toContain("sort=first_message_at");
    expect(url).toContain("order=asc");
  });
});

// ── getSession ───────────────────────────────────────────

describe("getSession", () => {
  it("returns a single session", async () => {
    const session = { id: "abc", summary: "A session", project_path: "/proj", message_count: 3, first_message_at: "2025-01-01", last_message_at: "2025-01-02" };
    mockApiResponse(session);

    const result = await getSession("abc");
    expect(result.id).toBe("abc");
    expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining("/sessions/abc"));
  });
});

// ── getSessionEvents ─────────────────────────────────────

describe("getSessionEvents", () => {
  it("returns events for a session", async () => {
    const data = { data: [{ event_id: "e1", content_blocks: [] }], meta: { total: 1 } };
    mockApiResponse(data);

    const result = await getSessionEvents("abc");
    expect(result.data).toHaveLength(1);
    expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining("/sessions/abc/events"));
  });
});

// ── search ───────────────────────────────────────────────

describe("search", () => {
  it("returns search results", async () => {
    const data = { data: [{ event_id: "e1", snippet: "found it" }], meta: { page: 1, per_page: 20, total: 1, pages: 1 } };
    mockApiResponse(data);

    const result = await search("hello");
    expect(result.data).toHaveLength(1);
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("q=hello");
  });

  it("passes pagination params", async () => {
    mockApiResponse({ data: [], meta: { page: 2, per_page: 10, total: 0, pages: 0 } });

    await search("hello", 2, 10);
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("page=2");
    expect(url).toContain("per_page=10");
  });
});

// ── getStats ─────────────────────────────────────────────

describe("getStats", () => {
  it("returns aggregate stats", async () => {
    const stats = {
      total_sessions: 3,
      total_events: 15,
      user_events: 8,
      assistant_events: 7,
      tool_uses: 4,
      total_tokens: 5000,
      cache_hit_rate: 0.42,
      per_model: [{ model: "claude-sonnet-4", tokens: 4000, events: 10 }],
      per_provider: [{ provider: "anthropic", tokens: 5000, events: 15 }],
    };
    mockApiResponse(stats);

    const result = await getStats();
    expect(result.total_sessions).toBe(3);
    expect(result.tool_uses).toBe(4);
    expect(result.cache_hit_rate).toBe(0.42);
    expect(result.per_model[0].model).toBe("claude-sonnet-4");
    expect(result.per_provider[0].provider).toBe("anthropic");
  });
});

// ── getDailyStats ────────────────────────────────────────

describe("getDailyStats", () => {
  it("returns daily stats with default 30 days", async () => {
    mockApiResponse({ data: [{ date: "2025-01-01", count: 5, tokens: 200 }] });

    const result = await getDailyStats();
    expect(result.data).toHaveLength(1);
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("days=30");
  });

  it("passes custom days param", async () => {
    mockApiResponse({ data: [] });

    await getDailyStats(7);
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("days=7");
  });
});

// ── getToolUsageStats ────────────────────────────────────

describe("getToolUsageStats", () => {
  it("returns tool usage rankings", async () => {
    mockApiResponse({ data: [{ tool_name: "Read", count: 10 }] });

    const result = await getToolUsageStats();
    expect(result.data[0].tool_name).toBe("Read");
  });
});

// ── triggerScan ──────────────────────────────────────────

describe("triggerScan", () => {
  it("triggers incremental scan via POST", async () => {
    mockApiResponse({ status: "ok", sessions: 1, events: 5, skipped: 0 });

    const result = await triggerScan();
    expect(result.status).toBe("ok");
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/scan"),
      expect.objectContaining({ method: "POST" }),
    );
  });
});

// ── triggerFullScan ──────────────────────────────────────

describe("triggerFullScan", () => {
  it("triggers full scan via POST", async () => {
    mockApiResponse({ status: "ok", sessions: 2, events: 10, skipped: 0 });

    const result = await triggerFullScan();
    expect(result.events).toBe(10);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/scan/full"),
      expect.objectContaining({ method: "POST" }),
    );
  });
});
