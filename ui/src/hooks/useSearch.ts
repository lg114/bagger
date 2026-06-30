import { useQuery } from "@tanstack/react-query";
import { search } from "../lib/api";

export function useSearch(query: string, page = 1) {
  return useQuery({
    queryKey: ["search", query, page],
    queryFn: () => search(query, page),
    enabled: query.length > 0,
  });
}
