import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import MemoriesPage from "@/pages/MemoriesPage";
import type { Memory } from "@/lib/api";

// Both API functions are mocked; types still resolve from the real module.
const { mockSearchMemories, mockListMemories } = vi.hoisted(() => ({
  mockSearchMemories: vi.fn(),
  mockListMemories: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  searchMemories: (...args: unknown[]) => mockSearchMemories(...args),
  listMemories: (...args: unknown[]) => mockListMemories(...args),
}));

function makeMemory(overrides: Partial<Memory> = {}): Memory {
  return {
    id: 1,
    type: "fact",
    content: "Zvec is a local embedded vector database",
    topics: ["vector-db"],
    confidence: 0.9,
    source: "claude",
    session_id: "s1",
    event_id: "e1",
    created_at: "2026-06-30T12:00:00+00:00",
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <MemoriesPage />
    </MemoryRouter>,
  );
}

function typeAndSubmit(value: string) {
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value } });
  fireEvent.submit(input.closest("form")!);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockSearchMemories.mockResolvedValue({ query: "", mode: "hybrid", count: 0, results: [] });
  mockListMemories.mockResolvedValue({
    data: [],
    meta: { page: 1, per_page: 20, total: 0, pages: 0 },
  });
});

describe("MemoriesPage browse view", () => {
  it("loads all memories on mount via listMemories", async () => {
    mockListMemories.mockResolvedValue({
      data: [makeMemory({ id: 1, type: "fact", source: "claude" })],
      meta: { page: 1, per_page: 20, total: 1, pages: 1 },
    });

    renderPage();

    await waitFor(() =>
      expect(mockListMemories).toHaveBeenCalledWith({
        page: 1,
        perPage: 20,
        source: undefined,
        type: undefined,
      }),
    );
  });

  it("re-runs listMemories with the selected type when a type chip is clicked", async () => {
    mockListMemories.mockResolvedValue({
      data: [makeMemory({ id: 1, type: "fact", source: "claude" })],
      meta: { page: 1, per_page: 20, total: 1, pages: 1 },
    });

    renderPage();

    const factChip = await screen.findByRole("button", { name: /^fact$/i });
    fireEvent.click(factChip);

    await waitFor(() =>
      expect(mockListMemories).toHaveBeenLastCalledWith({
        page: 1,
        perPage: 20,
        source: undefined,
        type: "fact",
      }),
    );
  });

  it("shows every source from meta.sources in the facet, even when page 1 lacks it", async () => {
    // Page 1's rows are all codex, but the dataset also contains claude. The
    // facet must read meta.sources (full dataset), not the current page.
    mockListMemories.mockResolvedValue({
      data: [makeMemory({ id: 1, type: "fact", source: "codex" })],
      meta: { page: 1, per_page: 20, total: 1, pages: 1, sources: ["claude", "codex"] },
    });

    renderPage();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^codex$/i })).toBeInTheDocument(),
    );
    // claude is absent from the page-1 rows yet still surfaces as a chip.
    expect(screen.getByRole("button", { name: /^claude$/i })).toBeInTheDocument();
  });
});

describe("MemoriesPage source facet (search)", () => {
  it("renders one chip per distinct source after a search", async () => {
    mockSearchMemories.mockResolvedValue({
      query: "zvec",
      mode: "hybrid",
      count: 2,
      results: [
        makeMemory({ id: 1, source: "claude" }),
        makeMemory({ id: 2, source: "codex" }),
      ],
    });

    renderPage();
    typeAndSubmit("zvec");

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^claude$/i })).toBeInTheDocument(),
    );
    // Both distinct sources surface as chips (use role, not text — result rows
    // also render the source name via SourceBadge).
    expect(screen.getByRole("button", { name: /^codex$/i })).toBeInTheDocument();
    // The "All" reset chip is always present.
    expect(screen.getByRole("button", { name: /^All$/i })).toBeInTheDocument();
  });

  it("re-runs the search with the selected source when a chip is clicked", async () => {
    mockSearchMemories.mockResolvedValue({
      query: "zvec",
      mode: "hybrid",
      count: 2,
      results: [
        makeMemory({ id: 1, source: "claude" }),
        makeMemory({ id: 2, source: "codex" }),
      ],
    });

    renderPage();
    typeAndSubmit("zvec");

    const claudeChip = await screen.findByRole("button", { name: /^claude$/i });
    fireEvent.click(claudeChip);

    await waitFor(() =>
      expect(mockSearchMemories).toHaveBeenLastCalledWith("zvec", "hybrid", 20, "claude"),
    );
  });

  it("clears the source filter when All is clicked", async () => {
    mockSearchMemories.mockResolvedValue({
      query: "zvec",
      mode: "hybrid",
      count: 1,
      results: [makeMemory({ id: 1, source: "claude" })],
    });

    renderPage();
    typeAndSubmit("zvec");

    const claudeChip = await screen.findByRole("button", { name: /^claude$/i });
    fireEvent.click(claudeChip);
    await waitFor(() =>
      expect(mockSearchMemories).toHaveBeenLastCalledWith("zvec", "hybrid", 20, "claude"),
    );

    const allChip = screen.getByRole("button", { name: /^All$/i });
    fireEvent.click(allChip);

    await waitFor(() =>
      expect(mockSearchMemories).toHaveBeenLastCalledWith("zvec", "hybrid", 20, undefined),
    );
  });
});
