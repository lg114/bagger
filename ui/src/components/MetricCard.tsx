import type { LucideIcon } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";

interface MetricCardProps {
  label: string;
  value: string | number | undefined;
  icon: LucideIcon;
  /** CSS color for the accent dot, e.g. "var(--brand-500)". */
  color: string;
  isLoading?: boolean;
}

/**
 * Editorial KPI tile — accent dot + hairline label + display numeral.
 * Single source of truth for HomePage, StatsPage, and ImportPage so the
 * metric styling can't drift between pages.
 */
export function MetricCard({ label, value, icon: Icon, color, isLoading = false }: MetricCardProps) {
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
          {typeof value === "number" ? value.toLocaleString() : (value ?? "—")}
        </div>
      )}
    </div>
  );
}
