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
import { Separator } from "@/components/ui/separator";
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
      <div className="flex flex-col items-center py-16 text-muted-foreground">
        <AlertCircle className="w-8 h-8 mb-3 text-red-400/60" />
        <p className="text-sm">Failed to load session</p>
        <p className="text-xs mt-1 opacity-60">{(sessionError as Error).message}</p>
        <Button variant="ghost" size="sm" asChild className="mt-4">
          <Link to="/sessions">Back to sessions</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto p-8 space-y-6">
      {/* Back link */}
      <Button variant="ghost" size="sm" asChild className="-ml-3">
        <Link to="/sessions" className="gap-1.5 text-muted-foreground">
          <ArrowLeft className="w-4 h-4" />
          Sessions
        </Link>
      </Button>

      {/* Session metadata */}
      {sessionLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-6 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      ) : session ? (
        <div>
          <h1 className="text-lg font-semibold mb-3">
            {session.summary || "Untitled Session"}
          </h1>
          <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
            {session.project_path && (
              <span className="flex items-center gap-1">
                <Folder className="w-3 h-3" />
                {session.project_path}
              </span>
            )}
            <span className="flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              {formatDateShort(session.first_message_at) || "—"}
            </span>
            <span className="flex items-center gap-1">
              <MessageSquare className="w-3 h-3" />
              {session.message_count} messages
            </span>
          </div>
        </div>
      ) : null}

      <Separator />

      {/* Conversation */}
      {eventsError ? (
        <div className="flex flex-col items-center py-12 text-muted-foreground">
          <AlertCircle className="w-8 h-8 mb-3 text-red-400/60" />
          <p className="text-sm">Failed to load events</p>
          <p className="text-xs mt-1 opacity-60">{(eventsError as Error).message}</p>
        </div>
      ) : eventsLoading ? (
        <div className="space-y-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex gap-3">
              <Skeleton className="w-7 h-7 rounded-md" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-20 w-full rounded-lg" />
              </div>
            </div>
          ))}
        </div>
      ) : events.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <p className="text-sm">No events in this session</p>
        </div>
      ) : (
        <ConversationView events={events} />
      )}
    </div>
  );
}
