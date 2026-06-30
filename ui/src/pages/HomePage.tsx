import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import {
  Search,
  MessageSquare,
  Users,
  Zap,
  ArrowRight,
  Hash,
} from "lucide-react";
import { useStats } from "@/hooks/useStats";
import { useSessions } from "@/hooks/useSessions";
import { cn, formatDateShort, formatTokens } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export default function HomePage() {
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState("");
  const { data: stats, isLoading: statsLoading } = useStats();
  const { data: recentSessions, isLoading: sessionsLoading } = useSessions(1);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
    }
  };

  const recent = recentSessions?.data?.slice(0, 10) ?? [];

  const statCards = [
    {
      label: "Sessions",
      value: stats?.total_sessions,
      icon: MessageSquare,
      color: "text-green-400",
      bg: "bg-green-500/10",
    },
    {
      label: "Events",
      value: stats?.total_events,
      icon: Zap,
      color: "text-sky-400",
      bg: "bg-sky-500/10",
    },
    {
      label: "Messages",
      value: stats?.user_events,
      icon: Users,
      color: "text-violet-400",
      bg: "bg-violet-500/10",
    },
    {
      label: "Tokens",
      value: stats ? formatTokens(stats.total_tokens) : undefined,
      icon: Hash,
      color: "text-amber-400",
      bg: "bg-amber-500/10",
    },
  ];

  return (
    <div className="max-w-4xl mx-auto p-8 space-y-10">
      {/* Stats */}
      <div className="grid grid-cols-4 gap-4">
        {statCards.map((card) => (
          <div
            key={card.label}
            className="bg-card border border-border rounded-lg p-4 hover:border-ring/30 transition-colors"
          >
            <div className="flex items-center gap-2 mb-3">
              <div className={cn("w-8 h-8 rounded-md flex items-center justify-center", card.bg)}>
                <card.icon className={cn("w-4 h-4", card.color)} />
              </div>
            </div>
            {statsLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="text-2xl font-bold font-mono tabular-nums">
                {card.value ?? "—"}
              </div>
            )}
            <div className="text-xs text-muted-foreground mt-1">{card.label}</div>
          </div>
        ))}
      </div>

      {/* Search */}
      <form onSubmit={handleSearch} className="relative">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search conversations..."
          className="w-full pl-12 pr-4 py-3.5 bg-card border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring text-lg"
        />
        <Button
          type="submit"
          size="sm"
          className="absolute right-2 top-1/2 -translate-y-1/2"
          disabled={!searchQuery.trim()}
        >
          Search
        </Button>
      </form>

      {/* Recent */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold">Recent Sessions</h2>
          <Button variant="ghost" size="sm" asChild>
            <Link to="/sessions" className="gap-1">
              View all <ArrowRight className="w-3 h-3" />
            </Link>
          </Button>
        </div>

        {sessionsLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-[72px] w-full rounded-lg" />
            ))}
          </div>
        ) : recent.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground border border-dashed border-border rounded-lg">
            <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p className="text-sm">No sessions yet</p>
            <p className="text-xs mt-1 opacity-60">
              Run <code className="font-mono text-green-400">bagger scan</code> to import sessions
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {recent.map((session) => (
              <Link
                key={session.id}
                to={`/sessions/${session.id}`}
                className="block bg-card border border-border rounded-lg p-4 hover:bg-accent/50 hover:border-ring/30 transition-colors cursor-pointer"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">
                      {session.summary || "Untitled Session"}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1 truncate">
                      {session.project_path || "—"}
                    </p>
                  </div>
                  <div className="flex items-center gap-4 shrink-0">
                    <span className="text-xs text-muted-foreground tabular-nums">
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
