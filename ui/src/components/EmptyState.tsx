import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { LucideIcon } from "lucide-react";
import { FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";

interface EmptyStateAction {
  label: string;
  to: string;
}

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  /** Plain string or rich node (e.g. a <code> chip). */
  description?: ReactNode;
  action?: EmptyStateAction;
}

/**
 * Centered empty state, shared across all list/search pages so the
 * "nothing here" moment reads consistently. `description` accepts a ReactNode
 * to preserve inline code chips where the original markup had them.
 */
export function EmptyState({ icon: Icon = FolderOpen, title, description, action }: EmptyStateProps) {
  return (
    <div className="text-center py-20 text-muted-foreground glass-card-static p-12">
      {Icon && <Icon className="w-12 h-12 mx-auto mb-4 text-[var(--brand-500)] opacity-15" />}
      <p className="text-sm mb-2 font-display text-base text-foreground/80">{title}</p>
      {description && <p className="text-xs opacity-50 font-mono">{description}</p>}
      {action && (
        <Button
          variant="outline"
          size="sm"
          asChild
          className="mt-4 border-primary/15 hover:border-primary/35 hover:bg-primary/10 hover:text-primary transition-all duration-200"
        >
          <Link to={action.to}>{action.label}</Link>
        </Button>
      )}
    </div>
  );
}
