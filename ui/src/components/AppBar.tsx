import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";

interface AppBarProps {
  onToggleSidebar: () => void;
  sidebarOpen: boolean;
}

export default function AppBar({ onToggleSidebar, sidebarOpen }: AppBarProps) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");

  const handleSearch = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = query.trim();
      if (trimmed) {
        navigate(`/search?q=${encodeURIComponent(trimmed)}`);
      }
    },
    [query, navigate],
  );

  return (
    <header className="h-12 shrink-0 flex items-center gap-4 px-6 border-b border-border bg-surface">
      {/* Sidebar toggle — bagger logo */}
      <button
        onClick={onToggleSidebar}
        className="p-1.5 rounded-element text-muted-foreground hover:text-foreground hover:bg-muted transition-colors duration-200 focus:outline-none"
        title={sidebarOpen ? "折叠侧栏" : "展开侧栏"}
      >
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <clipPath id="bagLeft">
              <rect x="0" y="0" width="9" height="18" />
            </clipPath>
          </defs>
          <rect x="2" y="3" width="14" height="12" rx="2.5" fill="currentColor" clipPath="url(#bagLeft)" />
          <rect x="2" y="3" width="14" height="12" rx="2.5" stroke="currentColor" strokeWidth="1.4" />
        </svg>
      </button>

      {/* Global search */}
      <form onSubmit={handleSearch} className="flex-1 max-w-xl">
        <div className="relative flex items-center">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索会话、事件、代码…"
            className="w-full h-8 pl-8 pr-14 rounded-element bg-background border border-border text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-[var(--focus-ring)]/40 focus:shadow-[0_0_0_3px_rgba(139,92,246,0.15)] transition-all duration-200"
          />
          <kbd className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] font-mono text-muted-foreground/50 pointer-events-none border border-border rounded px-1.5 py-0.5 leading-none">
            ⌘K
          </kbd>
        </div>
      </form>
    </header>
  );
}
