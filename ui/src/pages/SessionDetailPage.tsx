import { useParams, Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Calendar, Folder, MessageSquare, Hash, AlertCircle, Search, Download } from "lucide-react";
import { getSession, getSessionEvents, getSessionTree, exportSessionMarkdown } from "@/lib/api";
import type { TreeNode, PaginatedMeta } from "@/lib/api";
import SessionTree from "@/components/SessionTree";
import { SourceBadge } from "@/components/SourceBadge";
import { formatDateShort, formatTokens } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import ConversationView from "@/components/ConversationView";
import type { Event } from "@/lib/api";

export default function SessionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const source = searchParams.get("source") ?? undefined;
  const [searchOpen, setSearchOpen] = useState(false);

  const { data: session, isLoading: sessLoading, error: sessError } = useQuery({
    queryKey: ["sessions", id, source],
    queryFn: () => getSession(id!, source),
    enabled: !!id,
  });

  const [view, setView] = useState<"transcript" | "topology">("transcript");

  const { data: treeData, isLoading: treeLoading } = useQuery({
    queryKey: ["sessions", id, source, "tree"],
    queryFn: () => getSessionTree(id!, source),
    enabled: !!id,
  });
  const tree: TreeNode[] = treeData?.data ?? [];

  // ── Conversation events: paginated, loaded incrementally ──
  // The backend paginates /sessions/{id}/events (page / per_page). We load
  // page 1 up front and append further pages on demand via loadMore / loadAll
  // so long sessions can be read end-to-end.
  const PAGE_SIZE = 50;

  const [events, setEvents] = useState<Event[]>([]);
  const [eventsMeta, setEventsMeta] = useState<PaginatedMeta | null>(null);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventsError, setEventsError] = useState<unknown>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadingAll, setLoadingAll] = useState(false);
  // Synchronous guard so two rapid clicks can't fire the same page fetch twice
  // (state-based guards lag a render behind the synchronous click handler).
  const fetchInFlight = useRef(false);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setEventsLoading(true);
    setEventsError(null);
    setEvents([]);
    setEventsMeta(null);
    getSessionEvents(id, source, 1, PAGE_SIZE)
      .then((resp) => {
        if (cancelled) return;
        setEvents(resp.data);
        setEventsMeta(resp.meta);
      })
      .catch((err) => {
        if (!cancelled) setEventsError(err);
      })
      .finally(() => {
        if (!cancelled) setEventsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id, source]);

  const hasMore = eventsMeta != null && eventsMeta.page < eventsMeta.pages;

  const loadMore = useCallback(async () => {
    if (!id || !eventsMeta || eventsMeta.page >= eventsMeta.pages) return;
    if (fetchInFlight.current) return;
    fetchInFlight.current = true;
    setLoadingMore(true);
    try {
      const next = eventsMeta.page + 1;
      const resp = await getSessionEvents(id, source, next, PAGE_SIZE);
      setEvents((prev) => [...prev, ...resp.data]);
      setEventsMeta(resp.meta);
    } catch (err) {
      setEventsError(err);
    } finally {
      setLoadingMore(false);
      fetchInFlight.current = false;
    }
  }, [id, source, eventsMeta]);

  const loadAll = useCallback(async () => {
    if (!id || !eventsMeta || eventsMeta.page >= eventsMeta.pages) return;
    if (fetchInFlight.current) return;
    fetchInFlight.current = true;
    setLoadingAll(true);
    try {
      // Walk every remaining page from the current cursor, accumulating all
      // events. Reuses the page count reported by the backend each response.
      let cursor = eventsMeta;
      let all = [...events];
      while (cursor.page < cursor.pages) {
        const next = cursor.page + 1;
        const resp = await getSessionEvents(id, source, next, PAGE_SIZE);
        all = [...all, ...resp.data];
        cursor = resp.meta;
      }
      setEvents(all);
      setEventsMeta(cursor);
    } catch (err) {
      setEventsError(err);
    } finally {
      setLoadingAll(false);
      fetchInFlight.current = false;
    }
  }, [id, source, events, eventsMeta]);

  const totalEvents = eventsMeta?.total ?? events.length;

  const isLoading = sessLoading || eventsLoading;
  const error = sessError || eventsError;

  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportDone, setExportDone] = useState<string | null>(null);

  // Clear the "exported → Downloads" note when switching to another session,
  // so it never shows a stale filename for the session currently on screen.
  useEffect(() => {
    setExportDone(null);
  }, [id]);

  async function handleExport() {
    if (!id || exporting) return;
    setExporting(true);
    setExportError(null);
    // Synchronous anchor click (see exportSessionMarkdown). The browser
    // downloads natively to the user's default Downloads folder. We can't
    // observe completion, so we surface the expected filename + destination
    // as confirmation instead of leaving the user guessing where it went.
    const filename = `bagger-${session?.source ?? "session"}-${id.slice(0, 24)}.md`;
    try {
      await exportSessionMarkdown(id, "markdown", source);
      setExportDone(filename);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Export failed");
    } finally {
      window.setTimeout(() => setExporting(false), 1200);
    }
  }

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
          <Button variant="ghost" size="sm" asChild className="-ml-3 mb-3 text-muted-foreground hover:text-foreground transition-colors duration-200">
            <Link to="/sessions">
            <ArrowLeft className="w-3.5 h-3.5 mr-1.5" />
            Conversations
          </Link>
        </Button>
        <div className="flex items-center gap-3">
          <h1 className="font-display text-2xl md:text-3xl font-medium tracking-tight flex-1 min-w-0 truncate text-foreground">
            {session.summary || "Untitled Session"}
          </h1>
          <button
            onClick={() => setSearchOpen((v) => !v)}
            className="shrink-0 flex items-center gap-2 px-3 py-2 rounded-element border border-border text-xs font-mono text-muted-foreground hover:text-primary hover:border-primary/35 transition-all duration-200"
            title="Search in conversation (Ctrl+F)"
          >
            <Search className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Search</span>
            <kbd className="hidden sm:inline ml-1 px-1.5 py-0.5 rounded bg-secondary text-[10px] text-muted-foreground border border-border">
              Ctrl+F
            </kbd>
          </button>
          <button
            onClick={handleExport}
            disabled={exporting}
            className="shrink-0 flex items-center gap-2 px-3 py-2 rounded-element border border-border text-xs font-mono text-muted-foreground hover:text-primary hover:border-primary/35 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
            title={exportError ? `Export failed: ${exportError}` : "Export this conversation as Markdown"}
          >
            <Download className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">{exporting ? "Exporting…" : "Export"}</span>
          </button>
        </div>
      </div>

      {exportError && (
        <p className="text-xs text-warning/80 font-mono mb-4">Export failed: {exportError}</p>
      )}

      {exportDone && !exportError && (
        <p className="text-xs text-primary/80 font-mono mb-4 flex items-center gap-1.5">
          <span className="text-primary">✓</span>
          Exported <span className="text-foreground/90">{exportDone}</span> → your browser&apos;s
          default <span className="text-foreground/90">Downloads</span> folder
        </p>
      )}

      <div className="flex flex-col gap-6 lg:flex-row lg:gap-8">
        {/* Main: conversation / topology */}
        <div className="flex-1 min-w-0 order-2 lg:order-1">
          <div className="flex items-center gap-1 mb-5 border-b border-border">
            {(["transcript", "topology"] as const).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`-mb-px pb-2 mr-5 text-sm font-medium transition-colors duration-200 border-b-2 ${
                  view === v
                    ? "border-[var(--brand-500)] text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                {v === "transcript" ? "Transcript" : "Topology"}
              </button>
            ))}
          </div>

          {view === "transcript" ? (
            events.length === 0 ? (
              <div className="text-center py-16 text-muted-foreground glass-card-static p-10">
                <MessageSquare className="w-10 h-10 mx-auto mb-4 text-primary/15" />
                <p className="text-sm">No events in this session</p>
              </div>
            ) : (
              <ConversationView
                events={events}
                hasMore={hasMore}
                loadingMore={loadingMore}
                loadingAll={loadingAll}
                total={totalEvents}
                onLoadMore={loadMore}
                onLoadAll={loadAll}
                searchOpen={searchOpen}
                onToggleSearch={() => setSearchOpen((v) => !v)}
                onCloseSearch={() => setSearchOpen(false)}
              />
            )
          ) : treeLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-full rounded-element bg-secondary/50" />
              ))}
            </div>
          ) : (
            <SessionTree tree={tree} />
          )}
        </div>

        {/* Right panel: metadata */}
        <aside className="w-full lg:w-[240px] lg:shrink-0 order-1 lg:order-2">
          <div className="glass-card-static p-5 space-y-3">
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Metadata</h3>

            {session.project_path && (
              <div className="space-y-1">
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Project</span>
                <Link
                  to={`/sessions?project=${encodeURIComponent(session.project_path)}`}
                  className="text-xs font-mono text-foreground/70 hover:text-[var(--brand-500)] flex items-center gap-1.5 truncate transition-colors duration-200"
                  title={session.project_path}
                >
                  <Folder className="w-3 h-3 shrink-0 text-primary/40" />
                  {session.project_path}
                </Link>
              </div>
            )}

            {session.source && (
              <div className="space-y-1">
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Source</span>
                <div className="flex items-center gap-1.5">
                  <SourceBadge source={session.source} />
                </div>
              </div>
            )}

            <div className="space-y-1">
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Timeline</span>
              <p className="text-xs font-mono text-foreground/70 flex items-center gap-1.5">
                <Calendar className="w-3 h-3 text-primary/40" />
                {formatDateShort(session.first_message_at || session.last_message_at)}
              </p>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-1 gap-3 pt-2 border-t border-border">
              <div>
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Messages</span>
                <p className="text-sm font-mono font-semibold text-foreground/80 mt-0.5 flex items-center gap-1">
                  <MessageSquare className="w-3 h-3 text-primary/40" />
                  {totalEvents}
                  {events.length < totalEvents && (
                    <span className="text-[10px] text-muted-foreground/70 font-normal">
                      ({events.length} loaded)
                    </span>
                  )}
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
