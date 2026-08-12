import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import MemoriesPage from "@/pages/MemoriesPage";
import type { Memory } from "@/lib/api";

// Runtime mock of the API; types still resolve from the real module.
const mockSearchMemories = vi.fn();
vi.mock("@/lib/api", () => ({
  searchMemories: (...args: unknown[]) => mockSearchMemories(...args),
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
    fused_score: 1,
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
});

describe("MemoriesPage source facet", () => {
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
