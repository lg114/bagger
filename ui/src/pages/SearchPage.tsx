import { useSearchParams } from "react-router-dom";
import { Search as SearchIcon, AlertCircle } from "lucide-react";
import { useSearch } from "@/hooks/useSearch";
import SearchBar from "@/components/SearchBar";
import SearchResults from "@/components/SearchResults";
import { Button } from "@/components/ui/button";

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q") || "";
  const page = parseInt(searchParams.get("page") || "1", 10);

  const { data, isLoading, error } = useSearch(query, page);

  const results = data?.data ?? [];
  const meta = data?.meta;

  const handleSearch = (q: string) => {
    setSearchParams({ q, page: "1" });
  };

  const handlePage = (p: number) => {
    setSearchParams({ q: query, page: String(p) });
  };

  return (
    <div className="max-w-5xl mx-auto space-y-8 animate-fade-in-up">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight mb-2">Search</h1>
        <p className="text-sm text-muted-foreground">
          Full-text search across all conversations
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
              {!isLoading && meta && (
                <p className="text-sm text-muted-foreground font-mono">
                  {meta.total} result{meta.total !== 1 ? "s" : ""} for{" "}
                  <span className="text-primary font-medium">"{query}"</span>
                  {meta.pages > 1 && (
                    <span className="ml-1 opacity-60">(page {meta.page} of {meta.pages})</span>
                  )}
                </p>
              )}

              <SearchResults results={results} isLoading={isLoading} query={query} />

              {!isLoading && results.length === 0 && (
                <div className="text-center py-20 text-muted-foreground glass-card-static p-16">
                  <SearchIcon className="w-12 h-12 mx-auto mb-4 text-primary/15" />
                  <p className="text-sm mb-2">No results found</p>
                  <p className="text-xs opacity-50">
                    Try different keywords or broader terms
                  </p>
                </div>
              )}

              {meta && meta.pages > 1 && (
                <div className="flex items-center justify-center gap-3 pt-6">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page <= 1}
                    onClick={() => handlePage(page - 1)}
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
                    onClick={() => handlePage(page + 1)}
                    className="border-primary/15 hover:border-primary/35 hover:bg-primary/10 hover:text-primary transition-all duration-300 ease-apple"
                  >
                    Next
                  </Button>
                </div>
              )}
            </>
          )}
        </>
      ) : (
        <div className="text-center py-20 text-muted-foreground glass-card-static p-16">
          <SearchIcon className="w-12 h-12 mx-auto mb-4 text-primary/15" />
          <p className="text-sm mb-2">Search your conversation history</p>
          <p className="text-xs opacity-50 font-mono">
            FTS5 with BM25 ranking. CJK falls back to LIKE.
          </p>
        </div>
      )}
    </div>
  );
}
