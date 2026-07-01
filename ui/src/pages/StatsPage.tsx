import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
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

// ── Daily activity chart ──

interface DayRow {
  date: string;
  shortDate: string;
  events: number;
  tokens: number;
}

function DailyChartSection() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["dailyStats"],
    queryFn: () => getDailyStats(30),
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
      <h2 className="text-xl font-semibold tracking-tight flex items-center gap-2.5">
        <TrendingUp className="w-5 h-5 text-primary" />
        Daily Activity
      </h2>
      {error ? (
        <ErrorBlock message="Failed to load daily stats" />
      ) : isLoading ? (
        <Skeleton className="h-56 w-full rounded-card bg-secondary/50" />
      ) : days.length === 0 ? (
        <div className="text-center py-12 text-sm text-muted-foreground glass-card-static p-8">
          No data yet
        </div>
      ) : (
        <div className="glass-card-static p-8">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart
              data={days}
              margin={{ top: 5, right: 10, left: -20, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#1f1f22" />
              <XAxis
                dataKey="shortDate"
                tick={{ fontSize: 11, fill: "#9ca3af" }}
                interval={Math.floor(days.length / 6)}
                axisLine={{ stroke: "#2a2a2f" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#9ca3af" }}
                axisLine={{ stroke: "#2a2a2f" }}
                tickLine={false}
                width={40}
              />
              <Tooltip
                contentStyle={{
                  background: "#0a0a0a",
                  border: "1px solid #2a2a2f",
                  borderRadius: 8,
                  fontSize: 12,
                  color: "#f8f9fa",
                  boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
                }}
                labelStyle={{ color: "#60a5fa", fontFamily: "JetBrains Mono, monospace" }}
                formatter={(value, name) => {
                  const num = Number(value ?? 0);
                  if (name === "tokens") return [formatTokens(num), "Tokens"];
                  return [num, "Events"];
                }}
              />
              <Bar
                dataKey="events"
                fill="#3b82f6"
                fillOpacity={0.35}
                radius={[4, 4, 0, 0]}
                activeBar={{
                  fill: "#60a5fa",
                  fillOpacity: 0.9,
                  stroke: "#60a5fa",
                  strokeWidth: 1,
                }}
              />
            </BarChart>
          </ResponsiveContainer>
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
        <div className="text-center py-12 text-sm text-muted-foreground glass-card-static p-8">
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
