import type { TreeNode } from "@/lib/api";

function TreeNodeItem({ node }: { node: TreeNode }) {
  return (
    <li>
      <div className="group flex items-center gap-3 py-1.5 pr-3 rounded-element border-l-2 border-transparent hover:border-[var(--brand-500)] hover:bg-[var(--bg-surface)] transition-all duration-200">
        <span
          className={`text-[10px] font-mono uppercase tracking-wider w-16 shrink-0 ${
            node.role === "assistant" ? "text-[var(--brand-500)]" : "text-muted-foreground"
          }`}
        >
          {node.role}
        </span>
        <span className="text-xs font-mono text-muted-foreground/70 w-20 shrink-0 tabular-nums">
          {node.timestamp?.slice(11, 19)}
        </span>
        <span className="text-[11px] font-mono text-foreground/40 truncate">
          {node.event_id}
        </span>
      </div>
      {node.children.length > 0 && (
        <ul className="ml-4 border-l border-border pl-2">
          {node.children.map((child) => (
            <TreeNodeItem key={child.event_id} node={child} />
          ))}
        </ul>
      )}
    </li>
  );
}

export default function SessionTree({ tree }: { tree: TreeNode[] }) {
  if (tree.length === 0) {
    return (
      <div className="text-center py-16 text-muted-foreground glass-card-static p-10">
        <p className="text-sm">No branch structure for this session</p>
      </div>
    );
  }
  return (
    <ul className="space-y-1">
      {tree.map((node) => (
        <TreeNodeItem key={node.event_id} node={node} />
      ))}
    </ul>
  );
}
