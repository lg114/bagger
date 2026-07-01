import { useParams, Link } from "react-router-dom";
import {
  ArrowLeft,
  Calendar,
  Folder,
  MessageSquare,
  AlertCircle,
} from "lucide-react";
import { useSession, useSessionEvents } from "@/hooks/useSessions";
import { formatDateShort } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import ConversationView from "@/components/ConversationView";

export default function SessionDetailPage() {
  const { id } = useParams<{ id: string }>();

  const {
    data: session,
    isLoading: sessionLoading,
    error: sessionError,
  } = useSession(id);

  const {
    data: eventsData,
    isLoading: eventsLoading,
    error: eventsError,
  } = useSessionEvents(id);

  const events = eventsData?.data ?? [];

  if (sessionError) {
    return (
      <div className="flex flex-col items-center py-20 text-muted-foreground animate-fade-in-up">
        <AlertCircle className="w-10 h-10 mb-4 text-warning/60" />
        <p className="text-sm">Failed to load session</p>
        <p className="text-xs mt-2 opacity-50 font-mono">{(sessionError as Error).message}</p>
        <Button variant="ghost" size="sm" asChild className="mt-6 text-primary hover:text-primary/70">
          <Link to="/sessions">Back to sessions</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-8 animate-fade-in-up">
      {/* Back link */}
      <Button variant="ghost" size="sm" asChild className="-ml-4 text-muted-foreground hover:text-primary transition-colors duration-300 ease-apple">
        <Link to="/sessions" className="gap-2">
          <ArrowLeft className="w-4 h-4" />
          Sessions
        </Link>
      </Button>

      {/* Session metadata */}
      {sessionLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-8 w-2/3 bg-secondary/50" />
          <Skeleton className="h-5 w-1/2 bg-secondary/50" />
        </div>
      ) : session ? (
        <div>
          <h1 className="text-2xl font-semibold tracking-tight mb-4">
            {session.summary || "Untitled Session"}
          </h1>
          <div className="flex flex-wrap items-center gap-5 text-xs text-muted-foreground font-mono">
            {session.project_path && (
              <span className="flex items-center gap-1.5 bg-primary/10 px-2.5 py-1 rounded-element border border-primary/15">
                <Folder className="w-3 h-3 text-primary/50" />
                {session.project_path}
              </span>
            )}
            <span className="flex items-center gap-1.5">
              <Calendar className="w-3 h-3 text-primary/40" />
              {formatDateShort(session.first_message_at) || "\u2014"}
            </span>
            <span className="flex items-center gap-1.5">
              <MessageSquare className="w-3 h-3 text-primary/40" />
              {session.message_count} messages
            </span>
          </div>
        </div>
      ) : null}

      {/* Separator */}
      <div className="h-px bg-primary/10" />

      {/* Conversation */}
      {eventsError ? (
        <div className="flex flex-col items-center py-16 text-muted-foreground">
          <AlertCircle className="w-10 h-10 mb-4 text-warning/60" />
          <p className="text-sm">Failed to load events</p>
          <p className="text-xs mt-2 opacity-50 font-mono">{(eventsError as Error).message}</p>
        </div>
      ) : eventsLoading ? (
        <div className="space-y-8">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex gap-4">
              <Skeleton className="w-9 h-9 rounded-element bg-secondary/50" />
              <div className="flex-1 space-y-3">
                <Skeleton className="h-24 w-full rounded-card bg-secondary/50" />
              </div>
            </div>
          ))}
        </div>
      ) : events.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground glass-card-static p-12">
          <p className="text-sm">No events in this session</p>
        </div>
      ) : (
        <ConversationView events={events} />
      )}
    </div>
  );
}
