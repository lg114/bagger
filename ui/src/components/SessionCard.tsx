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
      className="glass-card block p-5 cursor-pointer group"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium truncate tracking-tight">
            {session.summary || "Untitled Session"}
          </h3>
          {session.project_path && (
            <p className="flex items-center gap-1.5 mt-2 text-xs text-muted-foreground truncate font-mono">
              <Folder className="w-3 h-3 shrink-0 text-primary/40" />
              {session.project_path}
            </p>
          )}
        </div>
        <div className="flex items-center gap-4 shrink-0 text-xs text-muted-foreground">
          <span className="flex items-center gap-1 tabular-nums font-mono">
            <MessageSquare className="w-3 h-3 text-primary/30" />
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
        "glass-card-static p-5 animate-pulse",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 space-y-3">
          <div className="h-4 w-3/4 bg-secondary/50 rounded" />
          <div className="h-3 w-1/2 bg-secondary/50 rounded" />
        </div>
        <div className="flex gap-4">
          <div className="h-3 w-10 bg-secondary/50 rounded" />
          <div className="h-3 w-16 bg-secondary/50 rounded" />
        </div>
      </div>
    </div>
  );
}
