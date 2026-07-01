import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  Search,
  MessageSquare,
  Users,
  Zap,
  ArrowRight,
  Hash,
  AlertCircle,
  RefreshCw,
  X,
} from "lucide-react";
import { useStats } from "@/hooks/useStats";
import { useSessions } from "@/hooks/useSessions";
import { triggerScan } from "@/lib/api";
import { cn, formatDateShort, formatTokens } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export default function HomePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState("");
  const [scanning, setScanning] = useState(false);
  const { data: stats, isLoading: statsLoading, error: statsError } = useStats();
  const { data: recentSessions, isLoading: sessionsLoading, error: sessionsError } = useSessions(1);

  const handleScan = async () => {
    setScanning(true);
    try {
      await triggerScan();
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
    } catch {
      // Error shown via React Query state
    } finally {
      setScanning(false);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
    }
  };

  const recent = recentSessions?.data?.slice(0, 10) ?? [];

  const statCards = [
    { label: "Sessions", value: stats?.total_sessions, icon: MessageSquare, color: "text-success", bg: "bg-success/8" },
    { label: "Events", value: stats?.total_events, icon: Zap, color: "text-primary", bg: "bg-primary/10" },
    { label: "Messages", value: stats?.user_events, icon: Users, color: "text-info", bg: "bg-info/10" },
    { label: "Tokens", value: stats ? formatTokens(stats.total_tokens) : undefined, icon: Hash, color: "text-accent", bg: "bg-accent/10" },
  ];

  return (
    <div className="max-w-5xl mx-auto space-y-10 animate-fade-in-up">
      {/* Stats */}
      <div className="grid grid-cols-4 gap-6">
        {statCards.map((card) => (
          <div
            key={card.label}
            className="glass-card p-5"
          >
            <div className="flex items-center gap-2.5 mb-4">
              <div className={cn("w-9 h-9 rounded-element flex items-center justify-center border", card.bg, "border-primary/15")}>
                <card.icon className={cn("w-[18px] h-[18px]", card.color)} />
              </div>
              <span className="text-xs text-muted-foreground uppercase tracking-wider font-mono">{card.label}</span>
            </div>
            {statsError ? (
              <div className="flex flex-col items-center">
                <AlertCircle className="w-5 h-5 mb-1 text-warning/60" />
                <span className="text-xs text-muted-foreground">Error</span>
              </div>
            ) : statsLoading ? (
              <Skeleton className="h-10 w-24 bg-secondary/50" />
            ) : (
              <div className="text-[32px] font-bold font-mono tabular-nums tracking-tight animate-count-up">
                {card.value ?? "\u2014"}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Search — Hero input */}
      <form onSubmit={handleSearch} className="relative search-glow">
        <Search className="absolute left-5 top-1/2 -translate-y-1/2 w-5 h-5 text-primary/40" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search conversations..."
          className="w-full pl-14 pr-24 py-4 glass-card-static text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/35 text-lg transition-all duration-300 ease-apple"
        />
        <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-2">
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="h-8 w-8 flex items-center justify-center text-muted-foreground hover:text-primary transition-colors duration-200"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </form>

      {/* Recent */}
      <section>
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold tracking-tight">Recent Sessions</h2>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              onClick={handleScan}
              disabled={scanning}
              className={cn("border-primary/15 hover:border-primary/35 hover:bg-primary/10 hover:text-primary transition-all duration-300 ease-apple", scanning && "pulse-glow")}
            >
              <RefreshCw className={cn("w-3.5 h-3.5 mr-1.5", scanning && "animate-spin")} />
              {scanning ? "Scanning..." : "Scan"}
            </Button>
            <Button variant="ghost" size="sm" asChild className="text-muted-foreground hover:text-primary">
              <Link to="/sessions" className="gap-1.5">
                View all <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </Button>
          </div>
        </div>

        {sessionsError ? (
          <div className="flex flex-col items-center py-16 text-muted-foreground">
            <AlertCircle className="w-8 h-8 mb-4 text-warning/60" />
            <p className="text-sm">Failed to load sessions</p>
            <p className="text-xs mt-2 opacity-50 font-mono">{(sessionsError as Error).message}</p>
          </div>
        ) : sessionsLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-[76px] w-full rounded-card bg-secondary/50" />
            ))}
          </div>
        ) : recent.length === 0 ? (
          <div className="text-center py-16 text-muted-foreground glass-card-static p-12">
            <MessageSquare className="w-10 h-10 mx-auto mb-4 text-primary/15" />
            <p className="text-sm mb-1">No sessions yet</p>
            <Button
              variant="outline"
              size="sm"
              onClick={handleScan}
              disabled={scanning}
              className="mt-4 border-primary/15 hover:border-primary/35 hover:bg-primary/10 hover:text-primary pulse-glow transition-all duration-300 ease-apple h-[52px] px-6 text-sm font-semibold"
            >
              <RefreshCw className={cn("w-4 h-4 mr-2", scanning && "animate-spin")} />
              {scanning ? "Scanning..." : "Scan for sessions"}
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            {recent.map((session, i) => (
              <Link
                key={session.id}
                to={`/sessions/${session.id}`}
                className="glass-card block p-5 cursor-pointer animate-fade-in-up"
                style={{ animationDelay: `${i * 50}ms` }}
              >
                <div className="flex items-start justify-between gap-6">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate tracking-tight">
                      {session.summary || "Untitled Session"}
                    </p>
                    <p className="text-xs text-muted-foreground mt-2 truncate font-mono">
                      {session.project_path || "\u2014"}
                    </p>
                  </div>
                  <div className="flex items-center gap-5 shrink-0">
                    <span className="text-xs text-muted-foreground tabular-nums font-mono">
                      {session.message_count} msgs
                    </span>
                    <span className="text-xs text-muted-foreground font-mono">
                      {formatDateShort(session.last_message_at)}
                    </span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
