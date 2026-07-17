import { Link } from "react-router-dom";
import {
  FolderOpen,
  MessageCircle,
  Activity,
  Coins,
  Clock,
  ArrowRight,
  Search,
  RefreshCw,
} from "lucide-react";
import { useStats } from "@/hooks/useStats";
import { useSessions } from "@/hooks/useSessions";
import { formatTokens } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { MetricCard } from "@/components/MetricCard";
import { ErrorBlock } from "@/components/ErrorBlock";
import { EmptyState } from "@/components/EmptyState";
import { SessionRow } from "@/components/SessionRow";

export default function HomePage() {
  const { data: stats, isLoading: statsLoading, error: statsError } = useStats();
  const { data: recentSessions, isLoading: sessionsLoading, error: sessionsError } = useSessions(1);

  const recent = recentSessions?.data?.slice(0, 8) ?? [];

  return (
    <div className="max-w-5xl mx-auto px-1 space-y-12 animate-fade-in-up">
      {/* Page header + quick actions */}
      <header className="pt-2 flex items-end justify-between gap-6">
        <div className="space-y-2">
          <h1 className="font-display text-3xl font-medium tracking-tight text-foreground">
            Dashboard
          </h1>
          <p className="text-sm text-muted-foreground">
            Your coding memory, at a glance.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            asChild
            className="text-muted-foreground hover:text-primary hover:bg-[var(--brand-bg)] gap-1.5"
          >
            <Link to="/search">
              <Search className="w-4 h-4" />
              Search
            </Link>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            asChild
            className="text-muted-foreground hover:text-primary hover:bg-[var(--brand-bg)] gap-1.5"
          >
            <Link to="/import">
              <RefreshCw className="w-4 h-4" />
              Scan
            </Link>
          </Button>
        </div>
      </header>

      {/* Overview metrics */}
      <section aria-label="Overview statistics">
        {statsError ? (
          <ErrorBlock message="Failed to load statistics" />
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              label="Sessions"
              value={stats?.total_sessions?.toLocaleString()}
              icon={FolderOpen}
              color="var(--brand-500)"
              isLoading={statsLoading}
            />
            <MetricCard
              label="Events"
              value={stats?.total_events?.toLocaleString()}
              icon={Activity}
              color="var(--node-topic)"
              isLoading={statsLoading}
            />
            <MetricCard
              label="Messages"
              value={stats?.user_events?.toLocaleString()}
              icon={MessageCircle}
              color="var(--success)"
              isLoading={statsLoading}
            />
            <MetricCard
              label="Tokens"
              value={stats ? formatTokens(stats.total_tokens) : undefined}
              icon={Coins}
              color="var(--warning)"
              isLoading={statsLoading}
            />
          </div>
        )}
      </section>

      {/* Recent sessions */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-xl font-medium tracking-tight text-foreground flex items-center gap-2">
            <Clock className="w-4 h-4 text-muted-foreground/50" />
            Recent Sessions
          </h2>
          <Button
            variant="ghost"
            size="sm"
            asChild
            className="text-muted-foreground hover:text-primary gap-1.5"
          >
            <Link to="/sessions">
              View all <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </Button>
        </div>

        {sessionsError ? (
          <ErrorBlock message="Failed to load sessions" detail={(sessionsError as Error).message} />
        ) : sessionsLoading ? (
          <div className="space-y-1">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-[60px] rounded-element animate-pulse bg-[var(--bg-elevated)]/50" />
            ))}
          </div>
        ) : recent.length === 0 ? (
          <EmptyState
            icon={FolderOpen}
            title="No sessions yet"
            action={{ label: "Go to Import", to: "/import" }}
          />
        ) : (
          <div className="rounded-card overflow-hidden border border-[var(--border-subtle)]">
            {recent.map((session) => (
              <SessionRow key={session.id} session={session} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
