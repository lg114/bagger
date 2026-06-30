import { Link } from "react-router-dom";
import { MessageSquare, Folder } from "lucide-react";
import { cn, formatDateShort } from "@/lib/utils";
import type { Session } from "@/lib/api";

interface SessionCardProps {
  session: Session;
}

export default function SessionCard({ session }: SessionCardProps) {
  return (
    <Link
      to={`/sessions/${session.id}`}
      className="block bg-card border border-border rounded-lg p-4 hover:bg-accent/50 hover:border-ring/30 transition-colors cursor-pointer"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium truncate">
            {session.summary || "Untitled Session"}
          </h3>
          {session.project_path && (
            <p className="flex items-center gap-1 mt-1.5 text-xs text-muted-foreground truncate">
              <Folder className="w-3 h-3 shrink-0" />
              {session.project_path}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0 text-xs text-muted-foreground">
          <span className="flex items-center gap-1 tabular-nums">
            <MessageSquare className="w-3 h-3" />
            {session.message_count}
          </span>
          <span className="font-mono">
            {formatDateShort(session.last_message_at || session.first_message_at)}
          </span>
        </div>
      </div>
    </Link>
  );
}

interface SessionCardSkeletonProps {
  className?: string;
}

export function SessionCardSkeleton({ className }: SessionCardSkeletonProps) {
  return (
    <div
      className={cn(
        "bg-card border border-border rounded-lg p-4 animate-pulse",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 space-y-2">
          <div className="h-4 w-3/4 bg-muted rounded" />
          <div className="h-3 w-1/2 bg-muted rounded" />
        </div>
        <div className="flex gap-3">
          <div className="h-3 w-10 bg-muted rounded" />
          <div className="h-3 w-16 bg-muted rounded" />
        </div>
      </div>
    </div>
  );
}
