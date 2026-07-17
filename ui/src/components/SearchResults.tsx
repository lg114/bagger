import { Link } from "react-router-dom";
import type { Event } from "@/lib/api";

interface SearchResultsProps {
  results: Event[];
  isLoading: boolean;
  query: string;
}

/**
 * Escape HTML, then style FTS5 <mark> tags with a clay highlight.
 * Uses color-mix against the --brand-500 token so the alpha actually applies
 * (Tailwind's `/15` modifier silently fails on an oklch CSS variable).
 */
function renderSnippet(raw: string): string {
  return raw
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(
      /&lt;mark&gt;/g,
      '<mark style="background:color-mix(in oklch,var(--brand-500) 15%,transparent);color:var(--brand-500)" class="rounded px-0.5">',
    )
    .replace(/&lt;\/mark&gt;/g, "</mark>");
}

export default function SearchResults({ results, isLoading }: SearchResultsProps) {
  if (isLoading) {
    return (
      <div className="rounded-card overflow-hidden border border-[var(--border-subtle)]">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="px-4 py-4 border-b border-[var(--border-subtle)] last:border-0 animate-pulse space-y-3"
          >
            <div className="flex items-center gap-3">
              <div className="h-4 w-16 rounded bg-[var(--bg-elevated)]/60" />
              <div className="h-3 w-32 rounded bg-[var(--bg-elevated)]/60" />
              <div className="h-3 w-16 rounded bg-[var(--bg-elevated)]/60 ml-auto" />
            </div>
            <div className="h-3 w-3/4 rounded bg-[var(--bg-elevated)]/60" />
          </div>
        ))}
      </div>
    );
  }

  if (results.length === 0) {
    return null;
  }

  return (
    <div className="rounded-card overflow-hidden border border-[var(--border-subtle)]">
      {results.map((event) => (
        <Link
          key={event.event_id}
          to={`/sessions/${event.session_id}`}
          className="group relative block border-b border-[var(--border-subtle)] last:border-0 before:absolute before:left-0 before:top-2.5 before:bottom-2.5 before:w-0.5 before:rounded-full before:bg-[var(--brand-500)] before:opacity-0 hover:before:opacity-100 transition-colors hover:bg-[var(--brand-bg)]"
        >
          <div className="px-4 py-4 space-y-2.5">
            {/* Meta row — role chip + timestamp + short session id */}
            <div className="flex items-center gap-3 flex-wrap">
              <span
                className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded-element font-mono border ${
                  event.role === "user"
                    ? "bg-[var(--brand-bg)] text-[var(--brand-500)] border-[var(--border-subtle)]"
                    : "bg-[var(--bg-elevated)] text-muted-foreground border border-[var(--border-subtle)]"
                }`}
              >
                {event.role}
              </span>
              <span className="text-xs text-muted-foreground font-mono tabular-nums">
                {event.timestamp?.slice(0, 19)?.replace("T", " ")}
              </span>
              <span className="text-xs text-muted-foreground truncate ml-auto font-mono opacity-50">
                {event.session_id.slice(0, 8)}
              </span>
            </div>

            {/* Snippet with FTS5 <mark> tags rendered as clay highlights */}
            {event.snippet ? (
              <p
                className="text-sm text-foreground/90 leading-relaxed"
                dangerouslySetInnerHTML={{ __html: renderSnippet(event.snippet) }}
              />
            ) : (
              <p className="text-sm text-muted-foreground leading-relaxed line-clamp-2">
                {event.content_text}
              </p>
            )}
          </div>
        </Link>
      ))}
    </div>
  );
}
