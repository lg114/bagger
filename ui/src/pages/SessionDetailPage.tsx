import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Calendar, Folder, MessageSquare, Hash, AlertCircle } from "lucide-react";
import { getSession, getSessionEvents } from "@/lib/api";
import { formatDateShort, formatTokens } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import ConversationView from "@/components/ConversationView";
import type { Event } from "@/lib/api";

export default function SessionDetailPage() {
  const { id } = useParams<{ id: string }>();

  const { data: session, isLoading: sessLoading, error: sessError } = useQuery({
    queryKey: ["sessions", id],
    queryFn: () => getSession(id!),
    enabled: !!id,
  });

  const { data: eventsData, isLoading: evtLoading, error: evtError } = useQuery({
    queryKey: ["sessions", id, "events"],
    queryFn: () => getSessionEvents(id!),
    enabled: !!id,
  });

  const events: Event[] = eventsData?.data ?? [];
  const isLoading = sessLoading || evtLoading;
  const error = sessError || evtError;

  // Loading
  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto space-y-6 animate-fade-in-up">
        <Skeleton className="h-8 w-64 bg-secondary/50" />
        <div className="space-y-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full rounded-card bg-secondary/50" />
          ))}
        </div>
      </div>
    );
  }

  // Error
  if (error || !session) {
    return (
      <div className="flex flex-col items-center py-20 text-muted-foreground animate-fade-in-up">
        <AlertCircle className="w-10 h-10 mb-4 text-warning/60" />
        <p className="text-sm mb-2">Session not found</p>
        <p className="text-xs mb-6 opacity-50 font-mono">{id}</p>
        <Button variant="ghost" size="sm" asChild className="text-primary hover:text-primary/70">
          <Link to="/sessions">
            <ArrowLeft className="w-3.5 h-3.5 mr-1.5" />
            Back to Sessions
          </Link>
        </Button>
      </div>
    );
  }

  const totalTokens = events.reduce((sum, e) => sum + (e.token_input || 0) + (e.token_output || 0), 0);

  return (
    <div className="max-w-6xl mx-auto animate-fade-in-up">
      {/* Header */}
      <div className="mb-6">
        <Button variant="ghost" size="sm" asChild className="-ml-3 mb-3 text-muted-foreground hover:text-primary transition-colors duration-200">
          <Link to="/sessions">
            <ArrowLeft className="w-3.5 h-3.5 mr-1.5" />
            Conversations
          </Link>
        </Button>
        <h1 className="text-2xl font-semibold tracking-tight">
          {session.summary || "Untitled Session"}
        </h1>
      </div>

      <div className="flex gap-8">
        {/* Main: conversation */}
        <div className="flex-1 min-w-0">
          {events.length === 0 ? (
            <div className="text-center py-16 text-muted-foreground glass-card-static p-10">
              <MessageSquare className="w-10 h-10 mx-auto mb-4 text-primary/15" />
              <p className="text-sm">No events in this session</p>
            </div>
          ) : (
            <ConversationView events={events} />
          )}
        </div>

        {/* Right panel: metadata */}
        <aside className="w-[240px] shrink-0 space-y-4">
          <div className="glass-card-static p-5 space-y-3">
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Metadata</h3>

            {session.project_path && (
              <div className="space-y-1">
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Project</span>
                <p className="text-xs font-mono text-foreground/70 flex items-center gap-1.5 truncate" title={session.project_path}>
                  <Folder className="w-3 h-3 shrink-0 text-primary/40" />
                  {session.project_path}
                </p>
              </div>
            )}

            <div className="space-y-1">
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Timeline</span>
              <p className="text-xs font-mono text-foreground/70 flex items-center gap-1.5">
                <Calendar className="w-3 h-3 text-primary/40" />
                {formatDateShort(session.first_message_at || session.last_message_at)}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3 pt-2 border-t border-border">
              <div>
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Messages</span>
                <p className="text-sm font-mono font-semibold text-foreground/80 mt-0.5 flex items-center gap-1">
                  <MessageSquare className="w-3 h-3 text-primary/40" />
                  {events.length}
                </p>
              </div>
              <div>
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Tokens</span>
                <p className="text-sm font-mono font-semibold text-foreground/80 mt-0.5 flex items-center gap-1">
                  <Hash className="w-3 h-3 text-primary/40" />
                  {formatTokens(totalTokens)}
                </p>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
