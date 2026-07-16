import { Link } from "react-router-dom";
import {
  FolderOpen,
  MessageCircle,
  Activity,
  Coins,
  AlertCircle,
  Clock,
  ArrowRight,
  Folder,
  MessageSquare,
  Search,
  RefreshCw,
  type LucideIcon,
} from "lucide-react";
import { useStats } from "@/hooks/useStats";
import { useSessions } from "@/hooks/useSessions";
import { formatDateShort, formatTokens } from "@/lib/utils";
import type { Session } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

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
          <EmptyState />
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

// ── Metric card (editorial: dot + hairline icon + display numeral) ──
function MetricCard({
  label,
  value,
  icon: Icon,
  color,
  isLoading,
}: {
  label: string;
  value: string | number | undefined;
  icon: LucideIcon;
  color: string;
  isLoading: boolean;
}) {
  return (
    <div className="glass-card p-5 group">
      <div className="flex items-center gap-2 mb-5">
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
        <span className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground font-mono">
          {label}
        </span>
        <Icon className="w-3.5 h-3.5 ml-auto text-muted-foreground/40 group-hover:text-foreground/50 transition-colors duration-200" />
      </div>
      {isLoading ? (
        <Skeleton className="h-9 w-16 rounded-md bg-[var(--bg-elevated)]/60" />
      ) : (
        <div className="font-display text-[34px] leading-none font-medium tabular-nums text-foreground animate-count-up">
          {value ?? "—"}
        </div>
      )}
    </div>
  );
}

// ── Session row (editorial hairline list, no nested cards) ──
function SessionRow({ session }: { session: Session }) {
  return (
    <Link
      to={`/sessions/${session.id}`}
      className="group relative block border-b border-[var(--border-subtle)] last:border-0 before:absolute before:left-0 before:top-2.5 before:bottom-2.5 before:w-0.5 before:rounded-full before:bg-[var(--brand-500)] before:opacity-0 hover:before:opacity-100 transition-colors hover:bg-[var(--brand-bg)]"
    >
      <div className="flex items-center justify-between gap-4 px-4 py-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-foreground truncate">
            {session.summary || "Untitled Session"}
          </p>
          {session.project_path && (
            <p className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground font-mono truncate">
              <Folder className="w-3 h-3 shrink-0 opacity-40" />
              {session.project_path}
            </p>
          )}
        </div>
        <div className="flex items-center gap-4 shrink-0 text-xs text-muted-foreground font-mono tabular-nums">
          <span className="flex items-center gap-1">
            <MessageSquare className="w-3 h-3 opacity-40" />
            {session.message_count}
          </span>
          <span>{formatDateShort(session.last_message_at)}</span>
        </div>
      </div>
    </Link>
  );
}

// ── Shared states ──
function ErrorBlock({ message, detail }: { message: string; detail?: string }) {
  return (
    <div className="flex flex-col items-center py-12 text-muted-foreground">
      <AlertCircle className="w-8 h-8 mb-3 text-warning/60" />
      <p className="text-sm font-mono">{message}</p>
      {detail && <p className="text-xs mt-2 opacity-50 font-mono">{detail}</p>}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="text-center py-12 text-muted-foreground glass-card-static p-10">
      <FolderOpen className="w-10 h-10 mx-auto mb-4 text-primary/15" />
      <p className="text-sm mb-1 font-display text-base text-foreground/80">No sessions yet</p>
      <Button
        variant="outline"
        size="sm"
        asChild
        className="mt-4 border-primary/15 hover:border-primary/35 hover:bg-primary/10 hover:text-primary transition-all duration-200"
      >
        <Link to="/import">Go to Import</Link>
      </Button>
    </div>
  );
}
