import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SourceBadge, sourceDotColor, SOURCE_DOT } from "../SourceBadge";

describe("SourceBadge", () => {
  it("renders the source name for a known source", () => {
    const { container } = render(<SourceBadge source="claude" />);
    expect(screen.getByText("claude")).toBeInTheDocument();
    expect(container.querySelector("span[title='source: claude']")).toBeTruthy();
  });

  it("renders nothing when source is missing", () => {
    const { container } = render(<SourceBadge source={undefined} />);
    expect(container.firstChild).toBeNull();
  });

  it("maps known sources to their accent dot color", () => {
    expect(sourceDotColor("claude")).toBe(SOURCE_DOT.claude);
    expect(sourceDotColor("chatgpt")).toBe(SOURCE_DOT.chatgpt);
  });

  it("falls back to the neutral dot for unknown sources", () => {
    expect(sourceDotColor("totally-unknown-tool")).toBe("oklch(60% 0.010 70)");
  });

  it("shows the raw source label for unknown sources", () => {
    render(<SourceBadge source="mystery-tool" />);
    expect(screen.getByText("mystery-tool")).toBeInTheDocument();
  });
});
