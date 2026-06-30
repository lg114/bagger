import { Link } from "react-router-dom";
import type { Event } from "@/lib/api";

interface SearchResultsProps {
  results: Event[];
  isLoading: boolean;
  query: string;
}

export default function SearchResults({
  results,
  isLoading,
  query,
}: SearchResultsProps) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="bg-card border border-border rounded-lg p-4 animate-pulse space-y-2"
          >
            <div className="h-3 w-24 bg-muted rounded" />
            <div className="h-4 w-3/4 bg-muted rounded" />
            <div className="h-3 w-1/2 bg-muted rounded" />
          </div>
        ))}
      </div>
    );
  }

  if (results.length === 0) {
    return null; // Handled by parent
  }

  return (
    <div className="space-y-2">
      {results.map((event) => (
        <Link
          key={event.event_id}
          to={`/sessions/${event.session_id}`}
          className="block bg-card border border-border rounded-lg p-4 hover:bg-accent/50 hover:border-ring/30 transition-colors cursor-pointer"
        >
          <div className="flex items-center gap-3 mb-2">
            <span
              className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${
                event.role === "user"
                  ? "bg-sky-500/10 text-sky-400"
                  : "bg-violet-500/10 text-violet-400"
              }`}
            >
              {event.role}
            </span>
            <span className="text-xs text-muted-foreground font-mono">
              {event.timestamp?.slice(0, 19)?.replace("T", " ")}
            </span>
            <span className="text-xs text-muted-foreground truncate ml-auto">
              {event.session_id.slice(0, 8)}
            </span>
          </div>

          {/* Snippet with FTS5 <mark> tags rendered as highlights */}
          {event.snippet ? (
            <p
              className="text-sm text-foreground/90 leading-relaxed"
              dangerouslySetInnerHTML={{
                __html: event.snippet.replace(
                  /<mark>/g,
                  '<mark class="bg-green-500/20 text-green-300 rounded px-0.5">',
                ),
              }}
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
