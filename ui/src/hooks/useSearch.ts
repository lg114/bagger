import { useQuery } from "@tanstack/react-query";
import { search } from "../lib/api";

export function useSearch(query: string, page = 1, source?: string) {
  return useQuery({
    queryKey: ["search", query, page, source],
    queryFn: () => search(query, page, 20, source),
    enabled: query.length > 0,
  });
}
