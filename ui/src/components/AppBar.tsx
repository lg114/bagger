import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Database } from "lucide-react";

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
    <header className="h-12 shrink-0 flex items-center gap-3 px-4 border-b border-border bg-surface">
      {/* Sidebar toggle + Logo */}
      <button
        onClick={onToggleSidebar}
        className="p-1.5 rounded-element text-muted-foreground hover:text-foreground hover:bg-muted transition-colors duration-200"
        title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
          <rect x="1" y="2" width="14" height="2" rx="1" />
          <rect x="1" y="7" width="14" height="2" rx="1" />
          <rect x="1" y="12" width="14" height="2" rx="1" />
        </svg>
      </button>

      <div className="flex items-center gap-2 mr-4 shrink-0">
        <div className="w-6 h-6 rounded bg-primary/10 flex items-center justify-center border border-primary/15">
          <Database className="w-3.5 h-3.5 text-primary" />
        </div>
        <span className="text-sm font-semibold tracking-tight">Bagger</span>
      </div>

      {/* Global search */}
      <form onSubmit={handleSearch} className="flex-1 max-w-xl">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search conversations... (Ctrl+K)"
            className="w-full h-8 pl-8 pr-3 rounded-element bg-background border border-border text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/35 transition-colors duration-200"
          />
        </div>
      </form>
    </header>
  );
}
