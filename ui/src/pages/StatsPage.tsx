import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  Coins,
  FolderOpen,
  MessageCircle,
  Wrench,
  TrendingUp,
  Bot,
  Zap,
  Cpu,
  Server,
  RefreshCw,
} from "lucide-react";
import { Link } from "react-router-dom";
import { getStats, getDailyStats, getToolUsageStats } from "@/lib/api";
import { formatTokens } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { MetricCard } from "@/components/MetricCard";
import { ErrorBlock } from "@/components/ErrorBlock";

export default function StatsPage() {
  return (
    <div className="max-w-5xl mx-auto px-1 space-y-12 animate-fade-in-up">
      {/* Page header + quick action */}
      <header className="pt-2 flex items-end justify-between gap-6">
        <div className="space-y-2">
          <h1 className="font-display text-3xl font-medium tracking-tight text-foreground">
            Analytics
          </h1>
          <p className="text-sm text-muted-foreground font-mono">
            Usage statistics and trends
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          asChild
          className="text-muted-foreground hover:text-primary hover:bg-[var(--brand-bg)] gap-1.5 shrink-0"
        >
          <Link to="/import">
            <RefreshCw className="w-4 h-4" />
            Scan
          </Link>
        </Button>
      </header>

      {/* KPI strip */}
      <KpiSection />

      {/* Centerpiece: daily activity contribution graph */}
      <DailyChartSection />

      {/* Breakdowns: model + provider side by side, tools full width */}
      <div className="grid gap-6 md:grid-cols-2">
        <ModelUsageSection />
        <ProviderUsageSection />
      </div>
      <ToolUsageSection />
    </div>
  );
}

// ── KPI strip ──

function KpiSection() {
  const { data: stats, isLoading, error } = useQuery({
    queryKey: ["stats"],
    queryFn: getStats,
  });

  const tiles: {
    label: string;
    value: string | number | undefined;
    icon: LucideIcon;
    color: string;
  }[] = [
    { label: "Sessions", value: stats?.total_sessions?.toLocaleString(), icon: FolderOpen, color: "var(--brand-500)" },
    { label: "Events", value: stats?.total_events?.toLocaleString(), icon: Activity, color: "var(--node-topic)" },
    { label: "User Messages", value: stats?.user_events?.toLocaleString(), icon: MessageCircle, color: "var(--success)" },
    { label: "Assistant", value: stats?.assistant_events?.toLocaleString(), icon: Bot, color: "var(--info)" },
    { label: "Tool Uses", value: stats?.tool_uses?.toLocaleString(), icon: Wrench, color: "var(--warning)" },
    { label: "Tokens", value: stats ? formatTokens(stats.total_tokens) : undefined, icon: Coins, color: "var(--brand-400)" },
    {
      label: "Cache Hit",
      value: stats?.cache_hit_rate != null ? `${(stats.cache_hit_rate * 100).toFixed(1)}%` : undefined,
      icon: Zap,
      color: "var(--success)",
    },
  ];

  return (
    <section aria-label="Key metrics">
      {error ? (
        <ErrorBlock message="Failed to load analytics" />
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
          {tiles.map((t) => (
            <MetricCard
              key={t.label}
              label={t.label}
              value={t.value}
              icon={t.icon}
              color={t.color}
              isLoading={isLoading}
            />
          ))}
        </div>
      )}
    </section>
  );
}

// ── Daily activity: GitHub-style contribution graph (clay editorial) ──

interface DayRow {
  date: string;
  shortDate: string;
  events: number;
  tokens: number;
}

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const CELL_PX = 12;
const GAP_PX = 3;

const LEVELS = [
  "var(--bg-elevated)",
  "color-mix(in oklch, var(--brand-500) 16%, transparent)",
  "color-mix(in oklch, var(--brand-500) 34%, transparent)",
  "color-mix(in oklch, var(--brand-500) 60%, transparent)",
  "color-mix(in oklch, var(--brand-500) 88%, transparent)",
];

function getLevel(count: number, max: number): number {
  if (count === 0) return 0;
  if (max <= 0) return 1;
  const ratio = count / max;
  if (ratio <= 0.25) return 1;
  if (ratio <= 0.50) return 2;
  if (ratio <= 0.75) return 3;
  return 4;
}

function ContributionGraph({ days, dayCount = 30 }: { days: DayRow[]; dayCount?: number }) {
  const [tooltip, setTooltip] = useState<{ x: number; y: number; date: string; count: number } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Default to the rightmost column (today) so users see recent activity first.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollLeft = el.scrollWidth - el.clientWidth;
  }, [days.length, dayCount]);

  const lookup = new Map<string, number>();
  for (const d of days) lookup.set(d.date, d.events || 0);
  const maxCount = Math.max(1, ...lookup.values());

  // Fixed window: today back dayCount days, aligned to Monday
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - dayCount + 1);
  const dow = start.getDay();
  start.setDate(start.getDate() - (dow === 0 ? 6 : dow - 1));

  const totalWeeks = Math.ceil((end.getTime() - start.getTime()) / (7 * 86400000)) + 1;

  // Build week columns
  const grid: { date: string; count: number }[][] = [];
  for (let w = 0; w < totalWeeks; w++) {
    const week: { date: string; count: number }[] = [];
    for (let d = 0; d < 7; d++) {
      const cd = new Date(start);
      cd.setDate(cd.getDate() + w * 7 + d);
      const key = cd.toISOString().slice(0, 10);
      week.push({ date: key, count: lookup.get(key) ?? 0 });
    }
    grid.push(week);
  }

  const months: { label: string; col: number; span: number }[] = [];
  let prevM = -1, monthStart = 0;
  for (let w = 0; w < grid.length; w++) {
    const m = new Date(grid[w][0].date + "T00:00:00").getMonth();
    if (m !== prevM) {
      if (prevM !== -1) {
        months[months.length - 1].span = w - monthStart;
      }
      months.push({ label: new Date(grid[w][0].date + "T00:00:00").toLocaleDateString("en-US", { month: "short" }), col: w, span: 1 });
      monthStart = w;
      prevM = m;
    }
  }
  if (months.length > 0) months[months.length - 1].span = grid.length - monthStart;

  const fmtDate = (s: string) =>
    new Date(s + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

  return (
    <div className="flex gap-3 w-full justify-center">
      <div className="flex flex-col shrink-0" style={{ paddingTop: 20, gap: GAP_PX }}>
        {DAY_LABELS.map((l, i) => (
          <span key={i} className="text-[10px] text-muted-foreground font-mono leading-none h-[12px] flex items-center justify-end w-8">{l}</span>
        ))}
      </div>

      <div className="flex flex-col min-w-0 flex-1">
        <div className="overflow-x-auto" ref={scrollRef}>
        <div className="flex min-w-fit" style={{ gap: GAP_PX, height: 20 }}>
          {months.map((m, i) => {
            if (m.span < 3 && i < months.length - 1) return null;
            return (
              <span
                key={m.col}
                className="text-[10px] text-muted-foreground font-mono leading-none flex items-end overflow-hidden"
                style={{ width: Math.max(m.span * (CELL_PX + GAP_PX) - GAP_PX, i === months.length - 1 ? 30 : 0) }}
              >
                {m.label}
              </span>
            );
          })}
        </div>

        <div className="flex min-w-fit" style={{ gap: GAP_PX }}>
          {grid.map((week, w) => (
            <div key={w} className="flex flex-col shrink-0" style={{ gap: GAP_PX, width: CELL_PX }}>
              {week.map((cell, d) => {
                const lv = getLevel(cell.count, maxCount);
                return (
                  <div key={d} className="relative" style={{ aspectRatio: "1", width: "100%" }}
                    onMouseEnter={(e) => {
                      const r = e.currentTarget.getBoundingClientRect();
                      setTooltip({ x: r.left + r.width / 2, y: r.top, date: cell.date, count: cell.count });
                    }}
                    onMouseLeave={() => setTooltip(null)}>
                    <div className="w-full h-full rounded-[2px]" style={{ backgroundColor: LEVELS[lv], cursor: cell.count > 0 ? "pointer" : "default" }} />
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {tooltip && createPortal(
          <div
            className="fixed z-50 pointer-events-none"
            style={{ left: tooltip.x, top: tooltip.y, transform: "translate(-50%, -100%)", marginTop: -6 }}
          >
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded px-2.5 py-1.5 text-[10px] font-mono whitespace-nowrap shadow-lg">
              <span className="text-foreground/90">{tooltip.count} events</span>
              <span className="text-muted-foreground ml-1.5">{fmtDate(tooltip.date)}</span>
            </div>
          </div>,
          document.body
        )}
        </div>

        <div className="flex items-center gap-1.5 mt-3">
          <span className="text-[10px] text-muted-foreground font-mono">Less</span>
          {LEVELS.map((c, i) => (
            <div key={i} className="rounded-[2px] shrink-0" style={{ width: CELL_PX, height: CELL_PX, backgroundColor: c }} />
          ))}
          <span className="text-[10px] text-muted-foreground font-mono">More</span>
        </div>
      </div>
    </div>
  );
}

function DailyChartSection() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["dailyStats"],
    queryFn: () => getDailyStats(365),
  });

  const rawDays = data?.data ?? [];

  const days: DayRow[] = rawDays.map((d) => ({
    date: d.date,
    shortDate: d.date.slice(5),
    events: d.count,
    tokens: d.tokens,
  }));

  return (
    <section className="space-y-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-display text-xl font-medium tracking-tight text-foreground flex items-center gap-2.5">
          <TrendingUp className="w-4 h-4 text-muted-foreground/50" />
          Daily Activity
        </h2>
        {days.length > 0 && (
          <span className="text-xs text-muted-foreground font-mono shrink-0">Past 365 days</span>
        )}
      </div>
      {error ? (
        <ErrorBlock message="Failed to load daily stats" />
      ) : isLoading ? (
        <Skeleton className="h-40 w-full rounded-card bg-[var(--bg-elevated)]/60" />
      ) : days.length === 0 ? (
        <div className="text-center py-12 text-sm text-muted-foreground glass-card-static p-6">
          No data yet
        </div>
      ) : (
        <div className="glass-card-static p-6 w-full overflow-hidden">
          <ContributionGraph days={days} dayCount={365} />
        </div>
      )}
    </section>
  );
}

// ── Ranked breakdown (editorial hairline list) ──

interface RankedItem {
  label: string;
  value: number;
}

function RankedCard({
  title,
  icon: Icon,
  items,
  loading,
  error,
  formatValue,
}: {
  title: string;
  icon: LucideIcon;
  items: RankedItem[];
  loading: boolean;
  error: unknown;
  formatValue: (v: number) => string;
}) {
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <section className="space-y-5">
      <h2 className="font-display text-xl font-medium tracking-tight text-foreground flex items-center gap-2.5">
        <Icon className="w-4 h-4 text-muted-foreground/50" />
        {title}
      </h2>
      {error ? (
        <ErrorBlock message={`Failed to load ${title.toLowerCase()}`} />
      ) : loading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full rounded-element bg-[var(--bg-elevated)]/60" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-10 text-sm text-muted-foreground glass-card-static p-6">
          No data yet
        </div>
      ) : (
        <div className="rounded-card overflow-hidden border border-[var(--border-subtle)]">
          {items.map((item, i) => (
            <div
              key={item.label}
              className="group flex items-center gap-4 px-5 py-3 border-b border-[var(--border-subtle)] last:border-0 hover:bg-[var(--brand-bg)] transition-colors duration-200"
            >
              <span className="text-xs text-muted-foreground font-mono w-5 tabular-nums shrink-0">{i + 1}</span>
              <span className="flex-1 text-sm font-mono text-foreground/80 truncate min-w-0">{item.label}</span>
              <div className="w-20 h-1.5 rounded-full overflow-hidden bg-[var(--bg-elevated)] shrink-0">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${(item.value / max) * 100}%`,
                    backgroundColor: "color-mix(in oklch, var(--brand-500) 45%, transparent)",
                  }}
                />
              </div>
              <span className="text-xs text-muted-foreground tabular-nums font-mono w-16 text-right shrink-0">
                {formatValue(item.value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ModelUsageSection() {
  const { data: stats, isLoading, error } = useQuery({
    queryKey: ["stats"],
    queryFn: getStats,
  });
  const items: RankedItem[] = (stats?.per_model ?? []).map((m) => ({
    label: m.model,
    value: m.tokens,
  }));
  return (
    <RankedCard
      title="By Model"
      icon={Cpu}
      items={items}
      loading={isLoading}
      error={error}
      formatValue={formatTokens}
    />
  );
}

function ProviderUsageSection() {
  const { data: stats, isLoading, error } = useQuery({
    queryKey: ["stats"],
    queryFn: getStats,
  });
  const items: RankedItem[] = (stats?.per_provider ?? []).map((p) => ({
    label: p.provider,
    value: p.tokens,
  }));
  return (
    <RankedCard
      title="By Provider"
      icon={Server}
      items={items}
      loading={isLoading}
      error={error}
      formatValue={formatTokens}
    />
  );
}

function ToolUsageSection() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["toolUsage"],
    queryFn: () => getToolUsageStats(15),
  });
  const items: RankedItem[] = (data?.data ?? []).map((t) => ({
    label: t.tool_name,
    value: t.count,
  }));
  return (
    <RankedCard
      title="Top Tools"
      icon={Wrench}
      items={items}
      loading={isLoading}
      error={error}
      formatValue={(v) => v.toLocaleString()}
    />
  );
}
