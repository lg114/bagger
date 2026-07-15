import { useSearchParams } from "react-router-dom";
import { MessageSquare, AlertCircle, X } from "lucide-react";
import { useSessions } from "@/hooks/useSessions";
import SessionCard, { SessionCardSkeleton } from "@/components/SessionCard";
import { Button } from "@/components/ui/button";

type SortKey = "last_message_at" | "message_count" | "first_message_at";

function basename(p: string): string {
  const parts = p.split("/").filter(Boolean);
  return parts[parts.length - 1] || p;
}

export default function SessionsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = parseInt(searchParams.get("page") || "1", 10);
  const sort = (searchParams.get("sort") || "last_message_at") as SortKey;

  const { data, isLoading, error } = useSessions(page, sort);

  const sessions = data?.data ?? [];
  const meta = data?.meta;
  const project = searchParams.get("project");
  const visibleSessions = project
    ? sessions.filter((s) => s.project_path === project)
    : sessions;

  const goToPage = (p: number) => {
    const params = new URLSearchParams(searchParams);
    params.set("page", String(p));
    setSearchParams(params);
  };

  const setSort = (key: SortKey) => {
    const params = new URLSearchParams(searchParams);
    params.set("sort", key);
    params.set("page", "1");
    setSearchParams(params);
  };

  const sortOptions: { key: SortKey; label: string }[] = [
    { key: "last_message_at", label: "Recent" },
    { key: "message_count", label: "Most Messages" },
    { key: "first_message_at", label: "Oldest" },
  ];

  return (
    <div className="max-w-5xl mx-auto space-y-6 animate-fade-in-up">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight mb-1">Conversations</h1>
          {meta && (
            <p className="text-sm text-muted-foreground font-mono">
              {meta.total} session{meta.total !== 1 ? "s" : ""}
              {meta.pages > 1 && (
                <span className="ml-2 opacity-50">page {meta.page} of {meta.pages}</span>
              )}
            </p>
          )}
          {project && (
            <div className="flex items-center gap-2 text-sm mt-1">
              <span className="text-muted-foreground">in</span>
              <span className="font-medium text-foreground">{basename(project)}</span>
              <button
                onClick={() => {
                  const p = new URLSearchParams(searchParams);
                  p.delete("project");
                  setSearchParams(p);
                }}
                className="text-muted-foreground hover:text-foreground transition-colors duration-200"
                title="Clear filter"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1 bg-muted rounded-element p-0.5">
          {sortOptions.map((opt) => (
            <button
              key={opt.key}
              onClick={() => setSort(opt.key)}
              className={`px-3 py-1.5 rounded text-xs font-mono transition-all duration-200 ${
                sort === opt.key
                  ? "bg-surface text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <div className="flex-1" />
      </div>

      {/* Content */}
      {error ? (
        <div className="flex flex-col items-center py-20 text-muted-foreground">
          <AlertCircle className="w-10 h-10 mb-4 text-warning/60" />
          <p className="text-sm">Failed to load sessions</p>
          <p className="text-xs mt-2 opacity-50 font-mono">{(error as Error).message}</p>
        </div>
      ) : isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <SessionCardSkeleton key={i} />
          ))}
        </div>
      ) : visibleSessions.length === 0 ? (
        <div className="text-center py-20 text-muted-foreground glass-card-static p-16">
          <MessageSquare className="w-12 h-12 mx-auto mb-4 text-primary/15" />
          <p className="text-sm mb-2">{project ? `No sessions in ${basename(project)}` : "No sessions found"}</p>
          <p className="text-xs opacity-50 font-mono">
            Run <code className="text-success bg-success/8 px-1.5 py-0.5 rounded border border-success/15">bagger scan</code> to import sessions
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {visibleSessions.map((session) => (
            <SessionCard key={session.id} session={session} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {meta && meta.pages > 1 && (
        <div className="flex items-center justify-center gap-3 pt-4">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => goToPage(page - 1)}
            className="border-primary/15 hover:border-primary/35 hover:bg-primary/10 hover:text-primary transition-all duration-200"
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
            className="border-primary/15 hover:border-primary/35 hover:bg-primary/10 hover:text-primary transition-all duration-200"
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
