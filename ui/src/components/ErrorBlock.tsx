import { AlertCircle } from "lucide-react";

interface ErrorBlockProps {
  message: string;
  detail?: string;
  className?: string;
}

/**
 * Centered inline error state. Shared by HomePage and StatsPage.
 * The warning icon uses an explicit opacity utility (not `text-warning/60`)
 * because `/<alpha>` modifiers don't apply to an oklch CSS variable.
 */
export function ErrorBlock({ message, detail, className }: ErrorBlockProps) {
  return (
    <div
      className={`flex flex-col items-center py-12 text-muted-foreground ${className ?? ""}`}
    >
      <AlertCircle className="w-8 h-8 mb-3 text-[var(--warning)] opacity-60" />
      <p className="text-sm font-mono">{message}</p>
      {detail && <p className="text-xs mt-2 opacity-50 font-mono">{detail}</p>}
    </div>
  );
}
