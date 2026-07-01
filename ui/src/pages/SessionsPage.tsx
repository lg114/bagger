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
    <div className="max-w-4xl mx-auto p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold mb-1">Sessions</h1>
          {meta && (
            <p className="text-sm text-muted-foreground">
              {meta.total} session{meta.total !== 1 ? "s" : ""}
            </p>
          )}
        </div>
      </div>

      {error ? (
        <div className="flex flex-col items-center py-16 text-muted-foreground">
          <AlertCircle className="w-8 h-8 mb-3 text-red-400/60" />
          <p className="text-sm">Failed to load sessions</p>
          <p className="text-xs mt-1 opacity-60">{(error as Error).message}</p>
        </div>
      ) : isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <SessionCardSkeleton key={i} />
          ))}
        </div>
      ) : sessions.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground border border-dashed border-border rounded-lg">
          <MessageSquare className="w-10 h-10 mx-auto mb-3 opacity-20" />
          <p className="text-sm">No sessions found</p>
          <p className="text-xs mt-1 opacity-60">
            Run <code className="font-mono text-green-400">bagger scan</code> to import sessions
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {sessions.map((session) => (
            <SessionCard key={session.id} session={session} />
          ))}
        </div>
      )}

      {meta && meta.pages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-4">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => goToPage(page - 1)}
          >
            Previous
          </Button>
          <span className="text-sm text-muted-foreground px-3">
            {page} / {meta.pages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= meta.pages}
            onClick={() => goToPage(page + 1)}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
