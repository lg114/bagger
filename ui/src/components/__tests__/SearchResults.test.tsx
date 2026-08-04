import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import SearchResults from "../SearchResults";
import type { Event } from "@/lib/api";

function makeEvent(overrides: Partial<Event> = {}): Event {
  return {
    event_id: "e1",
    session_id: "s1",
    timestamp: "2026-06-30T12:00:00+00:00",
    role: "user",
    content_blocks: [],
    token_input: 0,
    token_output: 0,
    snippet: "found it",
    ...overrides,
  };
}

function renderResults(results: Event[]) {
  return render(
    <MemoryRouter>
      <SearchResults results={results} isLoading={false} query="hello" />
    </MemoryRouter>,
  );
}

describe("SearchResults", () => {
  it("renders a source badge per result when source is present", () => {
    renderResults([makeEvent({ event_id: "e-codex", source: "codex" })]);
    const badge = screen.getByTitle("source: codex");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("codex");
  });

  it("renders no source badge when results lack a source", () => {
    const { container } = renderResults([
      makeEvent({ event_id: "e-plain", source: undefined }),
    ]);
    expect(container.querySelector("span[title^='source:']")).toBeNull();
  });

  it("shows a distinct badge for a different source", () => {
    renderResults([makeEvent({ event_id: "e-claude", source: "claude" })]);
    expect(screen.getByTitle("source: claude")).toHaveTextContent("claude");
  });
});
