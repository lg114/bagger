import { useSearchParams } from "react-router-dom";
import { MessageSquare, AlertCircle } from "lucide-react";
import { useSessions } from "@/hooks/useSessions";
import SessionCard, { SessionCardSkeleton } from "@/components/SessionCard";
import { Button } from "@/components/ui/button";

export default function SessionsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = parseInt(searchParams.get("page") || "1", 10);

  const { data, isLoading, error } = useSessions(page);

  const sessions = data?.data ?? [];
  const meta = data?.meta;

  const goToPage = (p: number) => {
    setSearchParams({ page: String(p) });
  };

  return (
    <div className="max-w-5xl mx-auto space-y-8 animate-fade-in-up">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight mb-2">Sessions</h1>
          {meta && (
            <p className="text-sm text-muted-foreground font-mono">
              {meta.total} session{meta.total !== 1 ? "s" : ""}
            </p>
          )}
        </div>
      </div>

      {error ? (
        <div className="flex flex-col items-center py-20 text-muted-foreground">
          <AlertCircle className="w-10 h-10 mb-4 text-warning/60" />
          <p className="text-sm">Failed to load sessions</p>
          <p className="text-xs mt-2 opacity-50 font-mono">{(error as Error).message}</p>
        </div>
      ) : isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <SessionCardSkeleton key={i} />
          ))}
        </div>
      ) : sessions.length === 0 ? (
        <div className="text-center py-20 text-muted-foreground glass-card-static p-16">
          <MessageSquare className="w-12 h-12 mx-auto mb-4 text-primary/15" />
          <p className="text-sm mb-2">No sessions found</p>
          <p className="text-xs opacity-50 font-mono">
            Run <code className="text-success bg-success/8 px-1.5 py-0.5 rounded border border-success/15">bagger scan</code> to import sessions
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {sessions.map((session) => (
            <SessionCard key={session.id} session={session} />
          ))}
        </div>
      )}

      {meta && meta.pages > 1 && (
        <div className="flex items-center justify-center gap-3 pt-6">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => goToPage(page - 1)}
            className="border-primary/15 hover:border-primary/35 hover:bg-primary/10 hover:text-primary transition-all duration-300 ease-apple"
          >
            Previous
          </Button>
          <span className="text-sm text-muted-foreground px-4 font-mono tabular-nums">
            {page} / {meta.pages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= meta.pages}
            onClick={() => goToPage(page + 1)}
            className="border-primary/15 hover:border-primary/35 hover:bg-primary/10 hover:text-primary transition-all duration-300 ease-apple"
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
