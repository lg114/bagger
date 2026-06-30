import { useQuery } from "@tanstack/react-query";
import { getStats, getDailyStats } from "../lib/api";

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: getStats,
  });
}

export function useDailyStats(days = 30) {
  return useQuery({
    queryKey: ["stats", "daily", days],
    queryFn: () => getDailyStats(days),
  });
}
