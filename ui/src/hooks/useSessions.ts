import { useQuery } from "@tanstack/react-query";
import { getSessions, getSession, getSessionEvents } from "../lib/api";

export function useSessions(page = 1, sort = "last_message_at", project?: string) {
  return useQuery({
    queryKey: ["sessions", page, sort, project],
    queryFn: () => getSessions(page, 50, sort, "desc", project),
  });
}

export function useSession(id: string | undefined) {
  return useQuery({
    queryKey: ["sessions", id],
    queryFn: () => getSession(id!),
    enabled: !!id,
  });
}

export function useSessionEvents(id: string | undefined) {
  return useQuery({
    queryKey: ["sessions", id, "events"],
    queryFn: () => getSessionEvents(id!),
    enabled: !!id,
  });
}
