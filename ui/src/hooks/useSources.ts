import { useQuery } from "@tanstack/react-query";
import { getSources } from "../lib/api";

/**
 * Canonical source facet for the Conversations / Search pages.
 *
 * Fetches the full set of distinct sources from the backend once (with an
 * optional project scope for the Conversations page) rather than inferring
 * them from the currently-loaded page — so a source whose sessions aren't on
 * the first page is still selectable.
 */
export function useSources(project?: string) {
  return useQuery({
    queryKey: ["sources", project ?? null],
    queryFn: () => getSources(project),
    staleTime: 60_000,
  });
}
