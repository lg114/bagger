import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useSearch } from "../useSearch";

// Mock the API module
const mockSearch = vi.fn();
vi.mock("../../lib/api", () => ({
  search: (...args: unknown[]) => mockSearch(...args),
}));

let queryClient: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
});

describe("useSearch", () => {
  it("is disabled when query is empty", () => {
    mockSearch.mockResolvedValue({ data: [], meta: { total: 0 } });

    const { result } = renderHook(() => useSearch(""), { wrapper });

    expect(result.current.isPending).toBe(true);
    expect(result.current.fetchStatus).toBe("idle");
    expect(mockSearch).not.toHaveBeenCalled();
  });

  it("fetches results when query is non-empty", async () => {
    mockSearch.mockResolvedValue({
      data: [{ event_id: "e1", snippet: "hello world" }],
      meta: { page: 1, per_page: 20, total: 1, pages: 1 },
    });

    const { result } = renderHook(() => useSearch("hello"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.data).toHaveLength(1);
    expect(result.current.data?.data[0].event_id).toBe("e1");
  });

  it("passes page param to API", async () => {
    mockSearch.mockResolvedValue({ data: [], meta: { total: 0 } });

    renderHook(() => useSearch("hello", 2), { wrapper });

    await waitFor(() => expect(mockSearch).toHaveBeenCalledWith("hello", 2, 20, undefined));
  });

  it("passes source param to API for multi-tool filtering", async () => {
    mockSearch.mockResolvedValue({ data: [], meta: { total: 0 } });

    renderHook(() => useSearch("hello", 1, "codex"), { wrapper });

    await waitFor(() => expect(mockSearch).toHaveBeenCalledWith("hello", 1, 20, "codex"));
  });

  it("keys the query on source so filters don't share cache", async () => {
    mockSearch.mockResolvedValue({ data: [], meta: { total: 0 } });

    const { rerender } = renderHook(
      ({ q, src }) => useSearch(q, 1, src),
      { wrapper, initialProps: { q: "hello", src: undefined as string | undefined } },
    );

    await waitFor(() => expect(mockSearch).toHaveBeenCalledTimes(1));
    rerender({ q: "hello", src: "codex" });
    await waitFor(() => expect(mockSearch).toHaveBeenCalledTimes(2));

    const keys = queryClient.getQueryCache().getAll().map((q) => q.queryKey);
    expect(keys).toContainEqual(["search", "hello", 1, undefined]);
    expect(keys).toContainEqual(["search", "hello", 1, "codex"]);
  });
});
