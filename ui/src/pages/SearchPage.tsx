import { useSearchParams } from "react-router-dom";
import { Search as SearchIcon, AlertCircle, Clock } from "lucide-react";
import { useSearch } from "@/hooks/useSearch";
import { useSources } from "@/hooks/useSources";
import SearchBar from "@/components/SearchBar";
import SearchResults from "@/components/SearchResults";
import { sourceDotColor } from "@/components/SourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q") || "";
  const page = parseInt(searchParams.get("page") || "1", 10);
  const source = searchParams.get("source");

  const { data, isLoading, error } = useSearch(query, page, source ?? undefined);
  const { data: facetSources } = useSources();
  const results = data?.data ?? [];
  const meta = data?.meta;

  // Canonical source facet from the backend (every distinct source across the
  // store), unioned with the active source so it always stays selectable.
  const sourceOptions = Array.from(
    new Set([...(facetSources ?? []), ...(source ? [source] : [])] as string[]),
  ).sort();

  const handleSearch = (q: string) => {
    setSearchParams({ q, page: "1" });
  };

  const handlePage = (p: number) => {
    const params = new URLSearchParams(searchParams);
    params.set("page", String(p));
    setSearchParams(params);
  };

  const setSource = (value: string) => {
    const params = new URLSearchParams(searchParams);
    if (value) params.set("source", value);
    else params.delete("source");
    params.set("page", "1");
    setSearchParams(params);
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6 animate-fade-in-up">
      <div>
        <h1 className="font-display text-3xl font-semibold tracking-tight mb-2 text-foreground">Search</h1>
        <p className="text-sm text-muted-foreground">
          Full-text search with BM25 ranking. Supports English and CJK.
        </p>
      </div>

      <SearchBar
        initialQuery={query}
        onSearch={handleSearch}
        autoFocus={!query}
      />

      {query ? (
        <>
          {error ? (
            <div className="flex flex-col items-center py-20 text-muted-foreground">
              <AlertCircle className="w-10 h-10 mb-4 text-warning/60" />
              <p className="text-sm">Failed to search</p>
              <p className="text-xs mt-2 opacity-50 font-mono">{(error as Error).message}</p>
            </div>
          ) : (
            <>
              {/* Results header */}
              {!isLoading && meta && (
                <div className="flex items-center gap-4">
                  <p className="text-sm text-muted-foreground font-mono">
                    <span className="text-primary font-medium">{meta.total}</span> result{meta.total !== 1 ? "s" : ""} for{" "}
                    <span className="text-primary font-medium">"{query}"</span>
                    {meta.pages > 1 && (
                      <span className="ml-2 opacity-50">(page {meta.page}/{meta.pages})</span>
                    )}
                  </p>
                  <div className="flex items-center gap-1 text-[10px] text-muted-foreground font-mono">
                    <Clock className="w-3 h-3" />
                    FTS5 BM25
                  </div>
                </div>
              )}

              {/* Source filter chips */}
              {!isLoading && sourceOptions.length > 0 && (
                <div className="flex items-center gap-1 bg-muted rounded-element p-0.5">
                  <button
                    onClick={() => setSource("")}
                    className={`px-3 py-1.5 rounded text-xs font-mono transition-all duration-200 ${
                      !source ? "bg-surface text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    All
                  </button>
                  {sourceOptions.map((s) => (
                    <button
                      key={s}
                      onClick={() => setSource(s)}
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

              <SearchResults results={results} isLoading={isLoading} query={query} />

              {!isLoading && results.length === 0 && (
                <EmptyState
                  icon={SearchIcon}
                  title="No results found"
                  description="Try different keywords or broader terms"
                />
              )}

              {meta && meta.pages > 1 && (
                <div className="flex items-center justify-center gap-3 pt-4">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page <= 1}
                    onClick={() => handlePage(page - 1)}
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
                    onClick={() => handlePage(page + 1)}
                    className="border-primary/15 hover:border-primary/35 hover:bg-primary/10 hover:text-primary transition-all duration-200"
                  >
                    Next
                  </Button>
                </div>
              )}
            </>
          )}
        </>
      ) : (
        <EmptyState
          icon={SearchIcon}
          title="Search your conversation history"
          description="Full-text search with BM25 ranking. CJK is tokenized with jieba."
        />
      )}
    </div>
  );
}
