import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SessionDetailPage from "@/pages/SessionDetailPage";

// Mock the session API; types still resolve from the real module.
const { mockGetSession, mockGetSessionEvents, mockGetSessionTree, mockExport } = vi.hoisted(
  () => ({
    mockGetSession: vi.fn(),
    mockGetSessionEvents: vi.fn(),
    mockGetSessionTree: vi.fn(),
    mockExport: vi.fn(),
  }),
);

vi.mock("@/lib/api", () => ({
  getSession: (...args: unknown[]) => mockGetSession(...args),
  getSessionEvents: (...args: unknown[]) => mockGetSessionEvents(...args),
  getSessionTree: (...args: unknown[]) => mockGetSessionTree(...args),
  exportSessionMarkdown: (...args: unknown[]) => mockExport(...args),
}));

function makeSession(source: string) {
  return {
    id: "abc",
    source,
    summary: `session from ${source}`,
    message_count: 3,
    project_path: "/p",
    first_message_at: "2026-01-01T00:00:00+00:00",
    last_message_at: "2026-01-02T00:00:00+00:00",
  };
}

function renderPage(initial = "/sessions/abc?source=codex") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        {/* Real app mounts the page under a /sessions/:id route, so useParams()
            resolves `id`. Mirror that here or the queries stay disabled. */}
        <Routes>
          <Route path="/sessions/:id" element={<SessionDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGetSession.mockResolvedValue(makeSession("claude"));
  mockGetSessionEvents.mockResolvedValue({ data: [], meta: { total: 0 } });
  mockGetSessionTree.mockResolvedValue({ data: [] });
});

describe("SessionDetailPage multi-source", () => {
  it("threads ?source= from the URL into every session API call", async () => {
    renderPage("/sessions/abc?source=codex");

    await waitFor(() => expect(mockGetSession).toHaveBeenCalledWith("abc", "codex"));
    expect(mockGetSessionEvents).toHaveBeenCalledWith("abc", "codex");
    expect(mockGetSessionTree).toHaveBeenCalledWith("abc", "codex");
  });

  it("omits source when the URL has none (legacy single-source behaviour)", async () => {
    renderPage("/sessions/abc");

    await waitFor(() => expect(mockGetSession).toHaveBeenCalledWith("abc", undefined));
  });

  it("renders the source-scoped session summary", async () => {
    mockGetSession.mockResolvedValue(makeSession("codex"));
    renderPage("/sessions/abc?source=codex");

    expect(await screen.findByText("session from codex")).toBeInTheDocument();
  });
});
