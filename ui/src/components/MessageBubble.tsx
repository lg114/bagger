import ContentBlockRenderer from "./ContentBlock";
import type { Event } from "@/lib/api";

interface MessageBubbleProps {
  event: Event;
  /** True when this message matches the current search query. */
  highlight?: boolean;
  /** True when this message is the *currently navigated* search match. */
  activeMatch?: boolean;
}

// Editorial thread: dot + text-label dual coding (color is never the only signal).
const ROLE_META: Record<string, { label: string; dot: string }> = {
  user: { label: "You", dot: "var(--brand-500)" },
  assistant: { label: "Assistant", dot: "var(--success)" },
  tool: { label: "Tool", dot: "var(--node-topic)" },
  error: { label: "Error", dot: "var(--error)" },
  system: { label: "System", dot: "var(--text-tertiary)" },
};

export default function MessageBubble({ event, highlight, activeMatch }: MessageBubbleProps) {
  const meta = ROLE_META[event.role] ?? {
    label: event.role || "Event",
    dot: "var(--text-tertiary)",
  };

  // Ring color for search matches (unchanged — tokens still exist).
  const ringClass = activeMatch
    ? "ring-2 ring-accent/60 ring-offset-2 ring-offset-background"
    : highlight
      ? "ring-1 ring-primary/30 ring-offset-1 ring-offset-background"
      : "";

  const tokens = (event.token_input || 0) + (event.token_output || 0);

  return (
    <article className={`relative min-w-0 ${ringClass} rounded-card`}>
      <div className="flex gap-3 min-w-0">
        {/* Dot gutter */}
        <div className="shrink-0 pt-1.5">
          <span
            className="block w-2 h-2 rounded-full"
            style={{ backgroundColor: meta.dot }}
            aria-hidden
          />
        </div>

        {/* Content column */}
        <div className="flex-1 min-w-0 space-y-1.5">
          {/* Label row — dual coded: colored dot above + neutral text label */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] font-medium text-secondary">{meta.label}</span>
            <span className="text-[10px] font-mono text-tertiary tabular-nums">
              {event.timestamp?.slice(11, 19) || ""}
            </span>
            {event.model && (
              <span className="text-[10px] font-mono text-tertiary/70 truncate max-w-[10rem] sm:max-w-[16rem]">{event.model}</span>
            )}
            {tokens > 0 && (
              <span className="text-[10px] font-mono text-tertiary/70 tabular-nums">
                {tokens} tok
              </span>
            )}
          </div>

          {/* Content card — calm bordered surface, no chat-bubble tint */}
          <div className="min-w-0 rounded-card border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3 transition-colors duration-300">
            {event.content_blocks?.length > 0 ? (
              <div className="space-y-3 min-w-0">
                {event.content_blocks.map((block, i) => (
                  <ContentBlockRenderer key={i} block={block} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground italic">Empty message</p>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}
