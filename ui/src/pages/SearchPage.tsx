import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Search as SearchIcon } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { search } from "@/lib/api";
import SearchBar from "@/components/SearchBar";
import SearchResults from "@/components/SearchResults";
import { Button } from "@/components/ui/button";

export default function SessionsPage() {
  return <SessionsPageInner />;
}

function SessionsPageInner() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q") || "";
  const page = parseInt(searchParams.get("page") || "1", 10);

  const { data, isLoading } = useQuery({
    queryKey: ["search", query, page],
    queryFn: () => search(query, page),
    enabled: query.length > 0,
  });

  const results = data?.data ?? [];
  const meta = data?.meta;

  const handleSearch = (q: string) => {
    setSearchParams({ q, page: "1" });
  };

  const handlePage = (p: number) => {
    setSearchParams({ q: query, page: String(p) });
  };

  return (
    <div className="max-w-4xl mx-auto p-8 space-y-6">
      <div>
        <h1 className="text-lg font-semibold mb-1">Search</h1>
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
          {!isLoading && meta && (
            <p className="text-sm text-muted-foreground">
              {meta.total} result{meta.total !== 1 ? "s" : ""} for{" "}
              <span className="text-foreground font-medium">"{query}"</span>
              {meta.pages > 1 && (
                <span className="ml-1">(page {meta.page} of {meta.pages})</span>
              )}
            </p>
          )}

          <SearchResults results={results} isLoading={isLoading} query={query} />

          {!isLoading && results.length === 0 && (
            <div className="text-center py-16 text-muted-foreground">
              <SearchIcon className="w-10 h-10 mx-auto mb-3 opacity-20" />
              <p className="text-sm">No results found</p>
              <p className="text-xs mt-1 opacity-60">
                Try different keywords or broader terms
              </p>
            </div>
          )}

          {meta && meta.pages > 1 && (
            <div className="flex items-center justify-center gap-2 pt-4">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => handlePage(page - 1)}
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
                onClick={() => handlePage(page + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </>
      ) : (
        <div className="text-center py-16 text-muted-foreground">
          <SearchIcon className="w-10 h-10 mx-auto mb-3 opacity-20" />
          <p className="text-sm">Search your conversation history</p>
          <p className="text-xs mt-1 opacity-60">
            English queries use FTS5 with BM25 ranking. CJK falls back to LIKE.
          </p>
        </div>
      )}
    </div>
  );
}
