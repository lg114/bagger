import { NavLink, Outlet } from "react-router-dom";
import {
  Home,
  MessageSquare,
  Search,
  BarChart3,
  Database,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { getHealth } from "@/lib/api";

const navItems = [
  { to: "/", icon: Home, label: "Home" },
  { to: "/sessions", icon: MessageSquare, label: "Sessions" },
  { to: "/search", icon: Search, label: "Search" },
  { to: "/stats", icon: BarChart3, label: "Stats" },
];

export default function Layout() {
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: (query) => query.state.data ? 60_000 : 2_000,
    retry: true,
  });

  return (
    <div className="flex h-screen">
      {/* Sidebar — Glass panel */}
      <aside className="w-[220px] shrink-0 flex flex-col glass-card-static rounded-none border-r border-primary/15"
        style={{ borderLeft: 'none', borderTop: 'none', borderBottom: 'none', borderRadius: '0' }}
      >
        {/* Logo */}
        <div className="h-14 flex items-center gap-2.5 px-5">
          <div className="w-7 h-7 rounded-element bg-primary/10 flex items-center justify-center border border-primary/15">
            <Database className="w-4 h-4 text-primary" />
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight leading-none">Bagger</div>
            <div className="text-[10px] text-muted-foreground leading-tight mt-0.5 font-mono">
              Memory Browser
            </div>
          </div>
        </div>

        {/* Separator */}
        <div className="h-px bg-primary/10 mx-3" />

        {/* Navigation */}
        <nav className="flex-1 p-3 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 px-3 py-2.5 rounded-element text-sm transition-all duration-300 ease-apple",
                  isActive
                    ? "bg-primary/10 text-primary font-medium border border-primary/15"
                    : "text-muted-foreground hover:text-foreground hover:bg-primary/5 cursor-pointer border border-transparent",
                )
              }
            >
              <item.icon className="w-[18px] h-[18px]" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* Separator */}
        <div className="h-px bg-primary/10 mx-3" />

        {/* Status */}
        <div className="px-5 py-4 text-xs text-muted-foreground">
          {health ? (
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "w-1.5 h-1.5 rounded-full shrink-0",
                  health.status === "ok" ? "bg-success" : "bg-warning",
                )}
              />
              <span className="font-mono tabular-nums">{health.sessions_count} sessions</span>
              <span className="ml-auto font-mono text-[10px] opacity-40">
                v{health.version}
              </span>
            </div>
          ) : (
            <div className="h-3 w-full bg-secondary rounded animate-pulse" />
          )}
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        <main className="flex-1 overflow-y-auto px-16 py-10">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
