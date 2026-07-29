import type { Session } from "@/lib/api";

/**
 * Source → accent color (calm, glare-friendly OKLCH from the design system).
 * Exported so the SessionsPage facet can reuse the same dot per source.
 * Unknown sources fall back to the neutral tertiary token.
 */
export const SOURCE_DOT: Record<string, string> = {
  claude: "oklch(64% 0.13 42)", // clay / terracotta (the native source → brand family)
  chatgpt: "oklch(72% 0.10 225)", // calm blue
  codex: "oklch(74% 0.13 155)", // sage green
  gemini: "oklch(70% 0.12 330)", // plum
  copilot: "oklch(78% 0.09 75)", // warm amber (file tone)
};

const SOURCE_FALLBACK_DOT = "oklch(60% 0.010 70)"; // --text-tertiary

export function sourceDotColor(source?: string): string {
  if (!source) return SOURCE_FALLBACK_DOT;
  return SOURCE_DOT[source] ?? SOURCE_FALLBACK_DOT;
}

/**
 * Tiny source pill — a colored dot + the source name. Used on every session
 * row (Dashboard "Recent" + Conversations) so the originating AI tool is
 * always visible at a glance (multi-tool support, §5.5 / (c)).
 *
 * Deliberately display-only (never a <button>/<a>): SessionRow is already a
 * <Link>, and nesting interactive elements inside a link is invalid HTML.
 */
export function SourceBadge({ source, className }: { source?: Session["source"]; className?: string }) {
  if (!source) return null;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border border-[var(--border-subtle)] bg-muted/40 px-2 py-0.5 text-[11px] font-mono leading-none text-muted-foreground ${
        className ?? ""
      }`}
      title={`source: ${source}`}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: sourceDotColor(source) }} />
      {source}
    </span>
  );
}
