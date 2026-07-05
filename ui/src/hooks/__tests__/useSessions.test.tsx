import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useSessions, useSession, useSessionEvents } from "../useSessions";

// Mock the API module
const mockGetSessions = vi.fn();
const mockGetSession = vi.fn();
const mockGetSessionEvents = vi.fn();

vi.mock("../../lib/api", () => ({
  getSessions: (...args: unknown[]) => mockGetSessions(...args),
  getSession: (...args: unknown[]) => mockGetSession(...args),
  getSessionEvents: (...args: unknown[]) => mockGetSessionEvents(...args),
}));

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useSessions", () => {
  it("fetches paginated sessions", async () => {
    mockGetSessions.mockResolvedValue({
      data: [
        { id: "s1", summary: "Test session", project_path: "/p", message_count: 5, first_message_at: "", last_message_at: "" },
      ],
      meta: { page: 1, per_page: 50, total: 1, pages: 1 },
    });

    const { result } = renderHook(() => useSessions(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.data).toHaveLength(1);
    expect(result.current.data?.data[0].id).toBe("s1");
  });

  it("passes page and sort params", async () => {
    mockGetSessions.mockResolvedValue({ data: [], meta: { total: 0 } });

    renderHook(() => useSessions(3, "first_message_at"), { wrapper });

    await waitFor(() =>
      expect(mockGetSessions).toHaveBeenCalledWith(3, 50, "first_message_at"),
    );
  });
});

describe("useSession", () => {
  it("returns a session when id is provided", async () => {
    mockGetSession.mockResolvedValue({
      id: "abc", summary: "Detail", project_path: "/p", message_count: 10, first_message_at: "", last_message_at: "",
    });

    const { result } = renderHook(() => useSession("abc"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe("abc");
    expect(result.current.data?.summary).toBe("Detail");
  });

  it("is disabled when id is undefined", () => {
    mockGetSession.mockResolvedValue({});

    const { result } = renderHook(() => useSession(undefined), { wrapper });

    expect(result.current.fetchStatus).toBe("idle");
    expect(mockGetSession).not.toHaveBeenCalled();
  });
});

describe("useSessionEvents", () => {
  it("fetches events for a session", async () => {
    mockGetSessionEvents.mockResolvedValue({
      data: [{ event_id: "e1", content_blocks: [] }],
      meta: { total: 1 },
    });

    const { result } = renderHook(() => useSessionEvents("abc"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.data).toHaveLength(1);
  });

  it("is disabled when id is undefined", () => {
    const { result } = renderHook(() => useSessionEvents(undefined), { wrapper });

    expect(result.current.fetchStatus).toBe("idle");
    expect(mockGetSessionEvents).not.toHaveBeenCalled();
  });
});
