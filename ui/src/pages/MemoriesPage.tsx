import { useState } from "react";
import { Search as SearchIcon, AlertCircle, Brain } from "lucide-react";
import { searchMemories, type Memory, type MemoryMode } from "@/lib/api";
import SearchBar from "@/components/SearchBar";
import { SourceBadge } from "@/components/SourceBadge";
import { EmptyState } from "@/components/EmptyState";

const MODES: { value: MemoryMode; label: string; hint: string }[] = [
  { value: "hybrid", label: "Hybrid", hint: "vector + BM25 fused" },
  { value: "vector", label: "Vector", hint: "semantic only" },
  { value: "fts", label: "FTS", hint: "keyword (offline)" },
];

// Calm, glare-friendly OKLCH per memory type (mirrors the design system).
const TYPE_COLOR: Record<string, string> = {
  fact: "oklch(74% 0.13 155)", // sage
  preference: "oklch(72% 0.10 225)", // blue
  decision: "oklch(70% 0.12 330)", // plum
  lesson: "oklch(78% 0.09 75)", // amber
};

export default function MemoriesPage() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<MemoryMode>("hybrid");
  const [results, setResults] = useState<Memory[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [searched, setSearched] = useState(false);

  const run = (q: string, m: MemoryMode = mode) => {
    const trimmed = q.trim();
    if (!trimmed) return;
    setQuery(trimmed);
    setSearched(true);
    setIsLoading(true);
    setError(null);
    searchMemories(trimmed, m)
      .then((res) => setResults(res.results))
      .catch((e) => setError(e as Error))
      .finally(() => setIsLoading(false));
  };

  const switchMode = (m: MemoryMode) => {
    setMode(m);
    if (searched) run(query, m);
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6 animate-fade-in-up">
      <div>
        <h1 className="font-display text-3xl font-semibold tracking-tight mb-2 text-foreground">
          Memories
        </h1>
        <p className="text-sm text-muted-foreground">
          Recall structured memories by meaning — not just keywords.
        </p>
      </div>

      <SearchBar initialQuery={query} onSearch={(q) => run(q)} autoFocus={!query} />

      {/* Retrieval mode toggle */}
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

      {!searched ? (
        <EmptyState
          icon={Brain}
          title="Recall your memories"
          description='Ask in natural language — e.g. “向量数据库选型”'
        />
      ) : error ? (
        <div className="flex flex-col items-center py-20 text-muted-foreground">
          <AlertCircle className="w-10 h-10 mb-4 text-warning/60" />
          <p className="text-sm">
            {String(error.message).includes("503")
              ? "Embedding service unavailable — try FTS mode, or set an embedding API key"
              : "Failed to search"}
          </p>
          <p className="text-xs mt-2 opacity-50 font-mono">{error.message}</p>
        </div>
      ) : (
        <>
          {!isLoading && (
            <p className="text-sm text-muted-foreground font-mono">
              <span className="text-primary font-medium">{results.length}</span> result
              {results.length !== 1 ? "s" : ""} for{" "}
              <span className="text-primary font-medium">"{query}"</span>
              <span className="ml-2 opacity-50">· {mode}</span>
            </p>
          )}

          <div className="space-y-3">
            {results.map((r) => (
              <article
                key={r.id}
                className="glass-card-static rounded-element p-4 space-y-2 animate-fade-in-up"
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-full border border-[var(--border-subtle)]"
                    style={{ color: TYPE_COLOR[r.type] ?? "var(--text-tertiary)" }}
                  >
                    {r.type}
                  </span>
                  <SourceBadge source={r.source} />
                  <span
                    className="ml-auto text-[10px] font-mono text-muted-foreground opacity-60"
                    title="fused RRF score"
                  >
                    {r.fused_score.toFixed(4)}
                  </span>
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

          {!isLoading && results.length === 0 && (
            <EmptyState
              icon={SearchIcon}
              title="No memories found"
              description="Try a different phrasing or the FTS mode"
            />
          )}
        </>
      )}
    </div>
  );
}
