import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useStats, useDailyStats } from "../useStats";

// Mock the API module
const mockGetStats = vi.fn();
const mockGetDailyStats = vi.fn();

vi.mock("../../lib/api", () => ({
  getStats: (...args: unknown[]) => mockGetStats(...args),
  getDailyStats: (...args: unknown[]) => mockGetDailyStats(...args),
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

describe("useStats", () => {
  it("fetches aggregate statistics", async () => {
    mockGetStats.mockResolvedValue({
      total_sessions: 4,
      total_events: 20,
      user_events: 10,
      assistant_events: 10,
      tool_uses: 3,
      total_tokens: 8000,
    });

    const { result } = renderHook(() => useStats(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.total_sessions).toBe(4);
    expect(result.current.data?.total_tokens).toBe(8000);
  });
});

describe("useDailyStats", () => {
  it("fetches daily stats with default 30 days", async () => {
    mockGetDailyStats.mockResolvedValue({
      data: [{ date: "2025-01-01", count: 3, tokens: 120 }],
    });

    const { result } = renderHook(() => useDailyStats(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.data).toHaveLength(1);
    expect(mockGetDailyStats).toHaveBeenCalledWith(30);
  });

  it("passes custom days param", async () => {
    mockGetDailyStats.mockResolvedValue({ data: [] });

    renderHook(() => useDailyStats(7), { wrapper });

    await waitFor(() => expect(mockGetDailyStats).toHaveBeenCalledWith(7));
  });
});
