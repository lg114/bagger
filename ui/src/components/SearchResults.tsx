import { Link } from "react-router-dom";
import type { Event } from "@/lib/api";

interface SearchResultsProps {
  results: Event[];
  isLoading: boolean;
  query: string;
}

/** Escape HTML special characters, then style FTS5 <mark> tags. */
function renderSnippet(raw: string): string {
  return raw
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/&lt;mark&gt;/g, '<mark class="bg-primary/15 text-primary rounded px-0.5">')
    .replace(/&lt;\/mark&gt;/g, "</mark>");
}

export default function SearchResults({
  results,
  isLoading,
}: SearchResultsProps) {
  if (isLoading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="glass-card-static p-5 animate-pulse space-y-3"
          >
            <div className="h-3 w-24 bg-secondary/50 rounded" />
            <div className="h-5 w-3/4 bg-secondary/50 rounded" />
            <div className="h-3 w-1/2 bg-secondary/50 rounded" />
          </div>
        ))}
      </div>
    );
  }

  if (results.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      {results.map((event) => (
        <Link
          key={event.event_id}
          to={`/sessions/${event.session_id}`}
          className="glass-card block p-5 cursor-pointer"
        >
          <div className="flex items-center gap-3 mb-3">
            <span
              className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded-element font-mono ${
                event.role === "user"
                  ? "bg-primary/10 text-primary border border-primary/15"
                  : "bg-info/10 text-info border border-info/15"
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

          {/* Snippet with FTS5 <mark> tags rendered as brand highlights */}
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
        </Link>
      ))}
    </div>
  );
}
