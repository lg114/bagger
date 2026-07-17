import { Link } from "react-router-dom";
import { Folder, MessageSquare } from "lucide-react";
import { formatDateShort } from "@/lib/utils";
import type { Session } from "@/lib/api";

/**
 * Editorial hairline session row — the single shared row used by both the
 * Dashboard "Recent Sessions" list and the Conversations page. Wrap in a
 * `rounded-card overflow-hidden border border-[var(--border-subtle)]` container;
 * the `border-b / last:border-0` lives on this <Link> (a direct child of that
 * container) so inter-row hairlines actually render and the last one drops cleanly.
 */
export function SessionRow({ session }: { session: Session }) {
  return (
    <Link
      to={`/sessions/${session.id}`}
      className="group relative block border-b border-[var(--border-subtle)] last:border-0 before:absolute before:left-0 before:top-2.5 before:bottom-2.5 before:w-0.5 before:rounded-full before:bg-[var(--brand-500)] before:opacity-0 hover:before:opacity-100 transition-colors hover:bg-[var(--brand-bg)]"
    >
      <div className="flex items-center justify-between gap-4 px-4 py-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-foreground truncate">
            {session.summary || "Untitled Session"}
          </p>
          {session.project_path && (
            <p className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground font-mono truncate">
              <Folder className="w-3 h-3 shrink-0 opacity-40" />
              {session.project_path}
            </p>
          )}
        </div>
        <div className="flex items-center gap-4 shrink-0 text-xs text-muted-foreground font-mono tabular-nums">
          <span className="flex items-center gap-1">
            <MessageSquare className="w-3 h-3 opacity-40" />
            {session.message_count}
          </span>
          <span>{formatDateShort(session.last_message_at)}</span>
        </div>
      </div>
    </Link>
  );
}

export function SessionRowSkeleton({ className }: { className?: string }) {
  return (
    <div
      className={`flex items-center justify-between gap-4 px-4 py-4 border-b border-[var(--border-subtle)] last:border-0 animate-pulse ${className ?? ""}`}
    >
      <div className="flex-1 min-w-0 space-y-3">
        <div className="h-4 w-3/4 rounded bg-[var(--bg-elevated)]/60" />
        <div className="h-3 w-1/2 rounded bg-[var(--bg-elevated)]/60" />
      </div>
      <div className="flex gap-4 shrink-0">
        <div className="h-3 w-10 rounded bg-[var(--bg-elevated)]/60" />
        <div className="h-3 w-16 rounded bg-[var(--bg-elevated)]/60" />
      </div>
    </div>
  );
}
