import { useState, useEffect } from "react";
import {
  Search as SearchIcon,
  AlertCircle,
  Brain,
  ArrowLeft,
  Archive,
  ArchiveRestore,
} from "lucide-react";
import {
  searchMemories,
  listMemories,
  setMemoryArchived,
  type Memory,
  type MemoryMode,
  type MemoryListResponse,
} from "@/lib/api";
import SearchBar from "@/components/SearchBar";
import { SourceBadge, sourceDotColor } from "@/components/SourceBadge";
import { EmptyState } from "@/components/EmptyState";

const MODES: { value: MemoryMode; label: string; hint: string }[] = [
  { value: "hybrid", label: "Hybrid", hint: "vector + BM25 fused" },
  { value: "vector", label: "Vector", hint: "semantic only" },
  { value: "fts", label: "FTS", hint: "keyword (offline)" },
];

const TYPES = ["fact", "preference", "decision", "lesson"] as const;

// Calm, glare-friendly OKLCH per memory type (mirrors the design system).
const TYPE_COLOR: Record<string, string> = {
  fact: "oklch(74% 0.13 155)", // sage
  preference: "oklch(72% 0.10 225)", // blue
  decision: "oklch(70% 0.12 330)", // plum
  lesson: "oklch(78% 0.09 75)", // amber
};

const PAGE_SIZE = 20;
const PAGE_SIZES = [20, 50, 100];

export default function MemoriesPage() {
  const [view, setView] = useState<"browse" | "search">("browse");
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<MemoryMode>("hybrid");
  const [source, setSource] = useState<string | null>(null);
  const [type, setType] = useState<string | null>(null);
  // false = live memories (archived=0, the default); true = the archive (archived=1).
  const [archivedView, setArchivedView] = useState(false);
  const [results, setResults] = useState<Memory[]>([]);
  const [meta, setMeta] = useState<MemoryListResponse["meta"] | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState<number>(PAGE_SIZE);
  const [searched, setSearched] = useState(false);
  // Memory id whose archive/restore PATCH is in flight — guards double-clicks.
  const [busyId, setBusyId] = useState<number | null>(null);

  const loadBrowse = (
    pg: number,
    s: string | null,
    t: string | null,
    pp: number = perPage,
    av: boolean = archivedView,
  ) => {
    setIsLoading(true);
    setError(null);
    listMemories({
      page: pg,
      perPage: pp,
      source: s ?? undefined,
      type: t ?? undefined,
      archived: av ? 1 : 0,
    })
      .then((res) => {
        setResults(res.data);
        setMeta(res.meta);
        setPage(pg);
      })
      .catch((e) => setError(e as Error))
      .finally(() => setIsLoading(false));
  };

  // First paint: load all memories (browse view).
  useEffect(() => {
    loadBrowse(1, null, null);
  }, []);

  const runSearch = (q: string, m: MemoryMode, s: string | null) => {
    const trimmed = q.trim();
    if (!trimmed) return;
    setView("search");
    setQuery(trimmed);
    setSearched(true);
    setIsLoading(true);
    setError(null);
    searchMemories(trimmed, m, PAGE_SIZE, s ?? undefined)
      .then((res) => setResults(res.results))
      .catch((e) => setError(e as Error))
      .finally(() => setIsLoading(false));
  };

  const switchMode = (m: MemoryMode) => {
    setMode(m);
    if (view === "search" && searched) runSearch(query, m, source);
  };

  const switchSource = (s: string | null) => {
    setSource(s);
    if (view === "browse") loadBrowse(1, s, type);
    else if (searched) runSearch(query, mode, s);
  };

  const switchType = (t: string | null) => {
    setType(t);
    if (view === "browse") loadBrowse(1, source, t);
  };

  const switchArchivedView = (archived: boolean) => {
    if (archived === archivedView) return;
    setArchivedView(archived);
    // Pass the new value explicitly: setState is async, so a plain loadBrowse
    // here would read the stale archivedView from the closure and reload the
    // wrong half of the dataset.
    loadBrowse(1, source, type, perPage, archived);
  };

  const backToBrowse = () => {
    setView("browse");
    setQuery("");
    setSearched(false);
    loadBrowse(1, source, type);
  };

  const changePerPage = (sz: number) => {
    setPerPage(sz);
    loadBrowse(1, source, type, sz);
  };

  // Archive (soft-delete) or restore a memory, then reload the current view so
  // the list reflects the server state. Browse: the record leaves the current
  // bucket (live → gone, archive → restored into live). Search: archived
  // memories are filtered server-side, so it simply disappears from results.
  const toggleArchive = (r: Memory) => {
    const target = r.archived === 1;
    if (busyId !== null) return;
    setBusyId(r.id);
    setError(null);
    setMemoryArchived(r.id, !target)
      .then(() => {
        if (view === "browse") loadBrowse(page, source, type);
        else if (searched) runSearch(query, mode, source);
      })
      .catch((e) => setError(e as Error))
      .finally(() => setBusyId(null));
  };

  // Browse view: the source facet comes from the FULL dataset (meta.sources),
  // so it stays complete across pagination — the current page may contain only
  // one source (e.g. the most recent 20 are all codex) and would otherwise hide
  // the others. Search view has no meta, so it falls back to the result set.
  const sourceOptions = Array.from(
    new Set([
      ...(view === "browse"
        ? (meta?.sources ?? [])
        : results.map((r) => r.source).filter(Boolean)),
      ...(source ? [source] : []),
    ] as string[]),
  ).sort();

  return (
    <div className="max-w-5xl mx-auto space-y-6 animate-fade-in-up">
      <div>
        <h1 className="font-display text-3xl font-semibold tracking-tight mb-2 text-foreground">
          Memories
        </h1>
        <p className="text-sm text-muted-foreground">
          {view === "search"
            ? "Recall structured memories by meaning — not just keywords."
            : "All structured memories, distilled from your conversations."}
        </p>
      </div>

      <SearchBar initialQuery={query} onSearch={(q) => runSearch(q, mode, source)} autoFocus={!query} />

      {/* Back to browse from a search */}
      {view === "search" && (
        <button
          onClick={backToBrowse}
          className="inline-flex items-center gap-1.5 text-xs font-mono text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> All memories
        </button>
      )}

      {/* Retrieval mode toggle — only meaningful in the search view */}
      {view === "search" && (
        <div className="flex items-center gap-1 bg-muted rounded-element p-0.5 w-fit">
          {MODES.map((m) => (
            <button
              key={m.value}
              onClick={() => switchMode(m.value)}
              className={`px-3 py-1.5 rounded text-xs font-mono transition-all duration-200 ${
                mode === m.value
                  ? "bg-surface text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              title={m.hint}
            >
              {m.label}
            </button>
          ))}
        </div>
      )}

      {/* Type facet — browse view only (the search endpoint has no type filter) */}
      {view === "browse" && meta && meta.total > 0 && (
        <div className="flex items-center gap-1 bg-muted rounded-element p-0.5 w-fit flex-wrap">
          <button
            onClick={() => switchType(null)}
            className={`px-3 py-1.5 rounded text-xs font-mono transition-all duration-200 ${
              !type ? "bg-surface text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            All
          </button>
          {TYPES.map((t) => (
            <button
              key={t}
              onClick={() => switchType(t)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono transition-all duration-200 ${
                type === t ? "bg-surface text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: TYPE_COLOR[t] }} />
              {t}
            </button>
          ))}
        </div>
      )}

      {/* Archive status — browse view only: live memories (default) or the archive. */}
      {view === "browse" && (
        <div className="flex items-center gap-1 bg-muted rounded-element p-0.5 w-fit">
          <button
            onClick={() => switchArchivedView(false)}
            className={`px-3 py-1.5 rounded text-xs font-mono transition-all duration-200 ${
              !archivedView ? "bg-surface text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
            title="Live memories — hidden from this view once archived"
          >
            Live
          </button>
          <button
            onClick={() => switchArchivedView(true)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono transition-all duration-200 ${
              archivedView ? "bg-surface text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
            title="Archived memories — restorable"
          >
            <Archive className="w-3 h-3" />
            Archived
          </button>
        </div>
      )}

      {/* Source facet — both views */}
      {sourceOptions.length > 0 && (
        <div className="flex items-center gap-1 bg-muted rounded-element p-0.5 w-fit flex-wrap">
          <button
            onClick={() => switchSource(null)}
            className={`px-3 py-1.5 rounded text-xs font-mono transition-all duration-200 ${
              !source ? "bg-surface text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            All
          </button>
          {sourceOptions.map((s) => (
            <button
              key={s}
              onClick={() => switchSource(s)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono transition-all duration-200 ${
                source === s ? "bg-surface text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: sourceDotColor(s) }} />
              {s}
            </button>
          ))}
        </div>
      )}

      {error ? (
        <div className="flex flex-col items-center py-20 text-muted-foreground">
          <AlertCircle className="w-10 h-10 mb-4 text-warning/60" />
          <p className="text-sm">
            {String(error.message).includes("503")
              ? "Embedding service unavailable — try FTS mode, or set an embedding API key"
              : "Failed to load memories"}
          </p>
          <p className="text-xs mt-2 opacity-50 font-mono">{error.message}</p>
        </div>
      ) : (
        <>
          {(
            <p className="text-sm text-muted-foreground font-mono">
              <span className="text-primary font-medium">{meta ? meta.total : results.length}</span>{" "}
              {view === "search" ? "result" : "memor"}
              {results.length !== 1 ? "ies" : "y"}
              {view === "search" && (
                <>
                  {" for "}
                  <span className="text-primary font-medium">"{query}"</span>
                  <span className="ml-2 opacity-50">· {mode}</span>
                </>
              )}
              {source && <span className="ml-2 opacity-50">· {source}</span>}
              {type && <span className="ml-2 opacity-50">· {type}</span>}
              {view === "browse" && archivedView && (
                <span className="ml-2 opacity-50">· archived</span>
              )}
            </p>
          )}

          <div
            key={`${view}-${source}-${type}-${page}-${perPage}-${query}-${archivedView}`}
            className="space-y-3 animate-fade-in"
          >
            {results.map((r) => (
              <article
                key={r.id}
                className="glass-card-static rounded-element p-4 space-y-2"
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-full border border-[var(--border-subtle)]"
                    style={{ color: TYPE_COLOR[r.type] ?? "var(--text-tertiary)" }}
                  >
                    {r.type}
                  </span>
                  <SourceBadge source={r.source} />
                  <div className="ml-auto flex items-center gap-2">
                    {r.fused_score != null && (
                      <span
                        className="text-[10px] font-mono text-muted-foreground opacity-60"
                        title="fused RRF score"
                      >
                        {r.fused_score.toFixed(4)}
                      </span>
                    )}
                    <button
                      onClick={() => toggleArchive(r)}
                      disabled={busyId === r.id}
                      className={`flex items-center gap-1 text-[11px] font-mono px-2 py-0.5 rounded transition-colors ${
                        r.archived === 1
                          ? "text-muted-foreground hover:text-primary"
                          : "text-muted-foreground opacity-70 hover:opacity-100 hover:text-primary"
                      } disabled:opacity-40 disabled:cursor-wait`}
                      title={
                        r.archived === 1
                          ? "Restore this memory so it shows up again"
                          : "Archive (soft-delete) — hidden from browse & retrieval, restorable"
                      }
                    >
                      {r.archived === 1 ? (
                        <ArchiveRestore className="w-3 h-3" />
                      ) : (
                        <Archive className="w-3 h-3" />
                      )}
                      {r.archived === 1 ? "Restore" : "Archive"}
                    </button>
                  </div>
                </div>

                <p className="text-sm text-foreground leading-relaxed">{r.content}</p>

                {r.topics && r.topics.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {r.topics.map((t) => (
                      <span
                        key={t}
                        className="text-[11px] font-mono text-muted-foreground bg-muted/40 rounded px-1.5 py-0.5"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </div>

          {/* Page size + pagination — browse view only */}
          {view === "browse" && meta && meta.total > 0 && (
            <div className="flex items-center justify-between gap-3 pt-2 flex-wrap">
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] font-mono text-muted-foreground">Per page</span>
                <div className="flex items-center gap-0.5 bg-muted rounded-element p-0.5">
                  {PAGE_SIZES.map((sz) => (
                    <button
                      key={sz}
                      onClick={() => changePerPage(sz)}
                      className={`px-2.5 py-1 rounded text-[11px] font-mono transition-all duration-200 ${
                        perPage === sz
                          ? "bg-surface text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {sz}
                    </button>
                  ))}
                </div>
              </div>
              {meta.pages > 1 && (
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => loadBrowse(Math.max(1, page - 1), source, type)}
                    disabled={page <= 1}
                    className="px-3 py-1.5 rounded text-xs font-mono bg-muted text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    ← Prev
                  </button>
                  <span className="text-xs font-mono text-muted-foreground">
                    {page} / {meta.pages}
                  </span>
                  <button
                    onClick={() => loadBrowse(Math.min(meta.pages, page + 1), source, type)}
                    disabled={page >= meta.pages}
                    className="px-3 py-1.5 rounded text-xs font-mono bg-muted text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    Next →
                  </button>
                </div>
              )}
            </div>
          )}

          {!isLoading && results.length === 0 && (
            <EmptyState
              icon={view === "search" ? SearchIcon : Brain}
              title={
                view === "search"
                  ? "No memories found"
                  : archivedView
                    ? "No archived memories"
                    : "No memories yet"
              }
              description={
                view === "search"
                  ? "Try a different phrasing or the FTS mode"
                  : archivedView
                    ? "Archived memories appear here — they stay restorable"
                    : "Run consolidation to distill memories from your conversations"
              }
            />
          )}
        </>
      )}
    </div>
  );
}
