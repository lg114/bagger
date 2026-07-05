import { Link } from "react-router-dom";
import { FolderOpen, MessageCircle, Activity, Coins, AlertCircle, Clock, ArrowRight, Folder } from "lucide-react";
import { useStats } from "@/hooks/useStats";
import { useSessions } from "@/hooks/useSessions";
import { cn, formatDateShort, formatTokens } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export default function HomePage() {
  const { data: stats, isLoading: statsLoading, error: statsError } = useStats();
  const { data: recentSessions, isLoading: sessionsLoading, error: sessionsError } = useSessions(1);

  const recent = recentSessions?.data?.slice(0, 8) ?? [];

  return (
    <div className="max-w-6xl mx-auto space-y-10 animate-fade-in-up">
      {/* Hero Stats */}
      <HeroStats stats={stats} isLoading={statsLoading} error={statsError} />

      {/* Recent sessions */}
      <div className="grid grid-cols-1 gap-6">
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold tracking-tight flex items-center gap-2">
              <Clock className="w-4 h-4 text-primary/60" />
              Recent Sessions
            </h2>
            <Button variant="ghost" size="sm" asChild className="text-muted-foreground hover:text-primary">
              <Link to="/sessions" className="gap-1.5">
                View all <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </Button>
          </div>

          {sessionsError ? (
            <ErrorBlock message="Failed to load sessions" detail={(sessionsError as Error).message} />
          ) : sessionsLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-[68px] w-full rounded-card bg-secondary/50" />
              ))}
            </div>
          ) : recent.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="space-y-2">
              {recent.map((session, i) => (
                <Link
                  key={session.id}
                  to={`/sessions/${session.id}`}
                  className="glass-card block px-5 py-6 cursor-pointer animate-fade-in-up"
                  style={{ animationDelay: `${i * 40}ms` }}
                >
                  <div className="flex items-center justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">
                        {session.summary || "Untitled Session"}
                      </p>
                      {session.project_path && (
                        <p className="text-xs text-muted-foreground mt-1.5 truncate font-mono flex items-center gap-1">
                          <Folder className="w-3 h-3 shrink-0 opacity-50" />
                          {session.project_path}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-4 shrink-0 text-xs text-muted-foreground font-mono">
                      <span>{session.message_count} msgs</span>
                      <span>{formatDateShort(session.last_message_at)}</span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

// ── Hero stat cards ──

function HeroStats({ stats, isLoading, error }: { stats: any; isLoading: boolean; error: any }) {
  const cards = [
    { label: "Sessions", value: stats?.total_sessions, icon: FolderOpen, color: "text-primary", bg: "bg-primary/10", border: "border-primary/15" },
    { label: "Events", value: stats?.total_events, icon: Activity, color: "text-pink-400", bg: "bg-pink-500/10", border: "border-pink-500/15" },
    { label: "Messages", value: stats?.user_events, icon: MessageCircle, color: "text-success", bg: "bg-success/8", border: "border-success/15" },
    { label: "Tokens", value: stats ? formatTokens(stats.total_tokens) : undefined, icon: Coins, color: "text-accent", bg: "bg-accent/10", border: "border-accent/15" },
  ];

  return (
    <div className="grid grid-cols-4 gap-6">
      {error ? (
        <div className="col-span-4">
          <ErrorBlock message="Failed to load statistics" />
        </div>
      ) : cards.map((card) => (
        <div key={card.label} className="glass-card p-6">
          <div className="flex items-center gap-2.5 mb-4">
            <div className={cn("w-9 h-9 rounded-element flex items-center justify-center border", card.bg, card.border)}>
              <card.icon className={cn("w-[18px] h-[18px]", card.color)} />
            </div>
            <span className="text-xs text-muted-foreground uppercase tracking-wider font-mono">{card.label}</span>
          </div>
          {isLoading ? (
            <Skeleton className="h-10 w-24 bg-secondary/50" />
          ) : (
            <div className="text-[32px] font-bold font-mono tabular-nums tracking-tight animate-count-up">
              {card.value ?? "\u2014"}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Shared components ──

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
      <p className="text-sm mb-1">No sessions yet</p>
      <Button variant="outline" size="sm" asChild className="mt-4 border-primary/15 hover:border-primary/35 hover:bg-primary/10 hover:text-primary transition-all duration-200">
        <Link to="/import">
          Go to Import
        </Link>
      </Button>
    </div>
  );
}
