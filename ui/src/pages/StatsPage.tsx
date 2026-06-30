import { useQuery } from "@tanstack/react-query";
import { Zap, Hash, MessageSquare, Users, Wrench, TrendingUp } from "lucide-react";
import { getStats, getDailyStats, getToolUsageStats } from "@/lib/api";
import { cn, formatTokens } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

export default function StatsPage() {
  return (
    <div className="max-w-4xl mx-auto p-8 space-y-8">
      <div>
        <h1 className="text-lg font-semibold mb-1">Statistics</h1>
        <p className="text-sm text-muted-foreground">Usage analytics and trends</p>
      </div>

      <StatsGrid />
      <DailyChartSection />
      <ToolUsageSection />
    </div>
  );
}

function StatsGrid() {
  const { data: stats, isLoading } = useQuery({
    queryKey: ["stats"],
    queryFn: getStats,
  });

  const cards = [
    { label: "Sessions", value: stats?.total_sessions, icon: MessageSquare, color: "text-green-400", bg: "bg-green-500/10" },
    { label: "Events", value: stats?.total_events, icon: Zap, color: "text-sky-400", bg: "bg-sky-500/10" },
    { label: "User Messages", value: stats?.user_events, icon: Users, color: "text-violet-400", bg: "bg-violet-500/10" },
    { label: "Assistant", value: stats?.assistant_events, icon: MessageSquare, color: "text-amber-400", bg: "bg-amber-500/10" },
    { label: "Tool Uses", value: stats?.tool_uses, icon: Wrench, color: "text-rose-400", bg: "bg-rose-500/10" },
    { label: "Tokens", value: stats ? formatTokens(stats.total_tokens) : undefined, icon: Hash, color: "text-teal-400", bg: "bg-teal-500/10" },
  ];

  return (
    <div className="grid grid-cols-3 gap-3">
      {cards.map((card) => (
        <div key={card.label} className="bg-card border border-border rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <div className={cn("w-7 h-7 rounded-md flex items-center justify-center", card.bg)}>
              <card.icon className={cn("w-3.5 h-3.5", card.color)} />
            </div>
            <span className="text-xs text-muted-foreground">{card.label}</span>
          </div>
          {isLoading ? (
            <Skeleton className="h-8 w-20" />
          ) : (
            <div className="text-2xl font-bold font-mono tabular-nums">
              {card.value ?? "—"}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function DailyChartSection() {
  const { data, isLoading } = useQuery({
    queryKey: ["dailyStats"],
    queryFn: () => getDailyStats(30),
  });

  const days = data?.data ?? [];
  const maxCount = Math.max(...days.map((d) => d.count), 1);
  const maxTokens = Math.max(...days.map((d) => d.tokens), 1);

  return (
    <section className="space-y-4">
      <h2 className="text-base font-semibold flex items-center gap-2">
        <TrendingUp className="w-4 h-4 text-green-400" />
        Daily Activity
      </h2>
      {isLoading ? (
        <Skeleton className="h-48 w-full rounded-lg" />
      ) : days.length === 0 ? (
        <div className="text-center py-8 text-sm text-muted-foreground border border-dashed border-border rounded-lg">
          No data yet
        </div>
      ) : (
        <div className="bg-card border border-border rounded-lg p-6">
          {/* Bar chart: events per day */}
          <div className="flex items-end gap-px h-32 mb-6">
            {days.map((d) => (
              <div
                key={d.date}
                className="flex-1 group relative"
                title={`${d.date}: ${d.count} events, ${formatTokens(d.tokens)}`}
              >
                <div
                  className="w-full bg-green-500/40 hover:bg-green-500/60 transition-colors rounded-t-sm"
                  style={{ height: `${Math.max((d.count / maxCount) * 100, 2)}%` }}
                />
                <div className="absolute -bottom-5 left-1/2 -translate-x-1/2 text-[8px] text-muted-foreground opacity-0 group-hover:opacity-100 whitespace-nowrap">
                  {d.count}
                </div>
              </div>
            ))}
          </div>
          {/* X-axis labels (every 5th day) */}
          <div className="flex items-end gap-px">
            {days.map((d, i) => (
              <div key={d.date} className="flex-1">
                {i % 5 === 0 && (
                  <div className="text-[9px] text-muted-foreground font-mono text-center">
                    {d.date.slice(5)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function ToolUsageSection() {
  const { data, isLoading } = useQuery({
    queryKey: ["toolUsage"],
    queryFn: () => getToolUsageStats(15),
  });

  const tools = data?.data ?? [];

  return (
    <section className="space-y-4">
      <h2 className="text-base font-semibold flex items-center gap-2">
        <Wrench className="w-4 h-4 text-amber-400" />
        Top Tools
      </h2>
      {isLoading ? (
        <div className="space-y-1.5">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full rounded" />
          ))}
        </div>
      ) : tools.length === 0 ? (
        <div className="text-center py-8 text-sm text-muted-foreground border border-dashed border-border rounded-lg">
          No tool usage recorded yet
        </div>
      ) : (
        <div className="bg-card border border-border rounded-lg divide-y divide-border">
          {tools.map((tool, i) => (
            <div key={tool.tool_name} className="flex items-center gap-3 px-4 py-2.5">
              <span className="text-xs text-muted-foreground font-mono w-5">{i + 1}</span>
              <span className="flex-1 text-sm font-mono text-foreground/80 truncate">
                {tool.tool_name}
              </span>
              <span className="text-xs text-muted-foreground tabular-nums">{tool.count}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
