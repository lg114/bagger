import { useQuery } from "@tanstack/react-query";
import { Circle, HardDrive } from "lucide-react";
import { getHealth } from "@/lib/api";

export default function StatusBar() {
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 60_000,
  });

  return (
    <footer className="h-7 shrink-0 flex items-center gap-4 px-6 bg-surface text-[11px] font-mono text-muted-foreground">
      {/* Sync status */}
      <span className="flex items-center gap-1.5">
        <Circle
          className="w-1.5 h-1.5 fill-current"
          style={{
            color: health?.status === "ok" ? "var(--success)" : "var(--warning)",
          }}
        />
        {health?.status === "ok" ? "Connected" : "Disconnected"}
      </span>

      {/* Stats */}
      {health && (
        <>
          <span>
            <strong className="text-foreground/60">{health.sessions_count.toLocaleString()}</strong> sessions
          </span>
          <span>
            <strong className="text-foreground/60">{health.events_count.toLocaleString()}</strong> events
          </span>
        </>
      )}

      {/* FTS status */}
      {health && (
        <span>
          FTS5:{" "}
          <strong className={health.fts_enabled ? "text-success" : "text-warning"}>
            {health.fts_enabled ? "ON" : "OFF"}
          </strong>
        </span>
      )}

      <span className="flex-1" />

      {/* DB path hint */}
      <span className="flex items-center gap-1 opacity-40">
        <HardDrive className="w-3 h-3" />
        ~/.bagger/bagger.db
      </span>
    </footer>
  );
}
