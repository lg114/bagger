import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Activity, Coins, FolderOpen, MessageCircle, Wrench, TrendingUp, AlertCircle, Bot } from "lucide-react";
import { getStats, getDailyStats, getToolUsageStats } from "@/lib/api";
import { cn, formatTokens } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

function ErrorBlock({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center py-12 text-muted-foreground">
      <AlertCircle className="w-8 h-8 mb-3 text-warning/60" />
      <p className="text-sm font-mono">{message}</p>
    </div>
  );
}

export default function StatsPage() {
  return (
    <div className="max-w-5xl mx-auto space-y-10 animate-fade-in-up">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight mb-2">Statistics</h1>
        <p className="text-sm text-muted-foreground">Usage analytics and trends</p>
      </div>

      <StatsGrid />
      <DailyChartSection />
      <ToolUsageSection />
    </div>
  );
}

// ── Stats card grid ──

function StatsGrid() {
  const { data: stats, isLoading, error } = useQuery({
    queryKey: ["stats"],
    queryFn: getStats,
  });

  const cards = [
    { label: "Sessions", value: stats?.total_sessions, icon: FolderOpen, color: "text-primary", bg: "bg-primary/10", border: "border-primary/15" },
    { label: "Events", value: stats?.total_events, icon: Activity, color: "text-pink-400", bg: "bg-pink-500/10", border: "border-pink-500/15" },
    { label: "User Messages", value: stats?.user_events, icon: MessageCircle, color: "text-success", bg: "bg-success/8", border: "border-success/15" },
    { label: "Assistant", value: stats?.assistant_events, icon: Bot, color: "text-cyan-400", bg: "bg-cyan-500/10", border: "border-cyan-500/15" },
    { label: "Tool Uses", value: stats?.tool_uses, icon: Wrench, color: "text-violet-400", bg: "bg-violet-500/10", border: "border-violet-500/15" },
    { label: "Tokens", value: stats ? formatTokens(stats.total_tokens) : undefined, icon: Coins, color: "text-accent", bg: "bg-accent/10", border: "border-accent/15" },
  ];

  return (
    <div className="grid grid-cols-3 gap-6">
      {error ? (
        <div className="col-span-3">
          <ErrorBlock message="Failed to load statistics" />
        </div>
      ) : cards.map((card) => (
        <div key={card.label} className="glass-card p-6">
          <div className="flex items-center gap-2.5 mb-3">
            <div className={cn("w-8 h-8 rounded-element flex items-center justify-center border", card.bg, card.border)}>
              <card.icon className={cn("w-[16px] h-[16px]", card.color)} />
            </div>
            <span className="text-xs text-muted-foreground uppercase tracking-wider font-mono">{card.label}</span>
          </div>
          {isLoading ? (
            <Skeleton className="h-10 w-24 bg-secondary/50" />
          ) : (
            <div className="text-[28px] font-bold font-mono tabular-nums tracking-tight animate-count-up">
              {card.value ?? "\u2014"}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Daily activity: GitHub-style contribution graph ──

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
  "#1a1a22",
  "rgba(45, 212, 191, 0.12)",
  "rgba(45, 212, 191, 0.28)",
  "rgba(45, 212, 191, 0.55)",
  "rgba(45, 212, 191, 0.85)",
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
            <div className="bg-[#0a0a0a] border border-[#2a2a2f] rounded px-2.5 py-1.5 text-[10px] font-mono whitespace-nowrap shadow-lg">
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
      <div className="flex items-baseline gap-3">
        <h2 className="text-xl font-semibold tracking-tight flex items-center gap-2.5">
          <TrendingUp className="w-5 h-5 text-primary" />
          Daily Activity
        </h2>
        {days.length > 0 && (
          <span className="text-xs text-muted-foreground font-mono">
            Past 365 days
          </span>
        )}
      </div>
      {error ? (
        <ErrorBlock message="Failed to load daily stats" />
      ) : isLoading ? (
        <Skeleton className="h-40 w-full rounded-card bg-secondary/50" />
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

// ── Tool usage ranked list ──

function ToolUsageSection() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["toolUsage"],
    queryFn: () => getToolUsageStats(15),
  });

  const tools = data?.data ?? [];
  const maxCount = Math.max(...tools.map((t) => t.count), 1);

  return (
    <section className="space-y-5">
      <h2 className="text-xl font-semibold tracking-tight flex items-center gap-2.5">
        <Wrench className="w-5 h-5 text-accent" />
        Top Tools
      </h2>
      {error ? (
        <ErrorBlock message="Failed to load tool usage" />
      ) : isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full rounded-element bg-secondary/50" />
          ))}
        </div>
      ) : tools.length === 0 ? (
        <div className="text-center py-12 text-sm text-muted-foreground glass-card-static p-6">
          No tool usage recorded yet
        </div>
      ) : (
        <div className="glass-card-static divide-y divide-primary/10">
          {tools.map((tool, i) => (
            <div key={tool.tool_name} className="flex items-center gap-4 px-6 py-4 hover:bg-primary/5 transition-colors duration-200 ease-out">
              <span className="text-xs text-muted-foreground font-mono w-5 tabular-nums">{i + 1}</span>
              <span className="flex-1 text-sm font-mono text-foreground/80 truncate">
                {tool.tool_name}
              </span>
              {/* Progress bar */}
              <div className="w-28 h-1.5 bg-secondary rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary/40 rounded-full transition-all duration-500 ease-apple"
                  style={{ width: `${(tool.count / maxCount) * 100}%` }}
                />
              </div>
              <span className="text-xs text-muted-foreground tabular-nums font-mono w-12 text-right">{tool.count}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
