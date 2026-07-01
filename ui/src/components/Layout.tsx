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
import { Separator } from "@/components/ui/separator";

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
    // Poll aggressively until backend is ready, then slow down
    refetchInterval: (query) => query.state.data ? 60_000 : 2_000,
    retry: true,
  });

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 border-r border-border flex flex-col">
        {/* Logo */}
        <div className="h-14 flex items-center gap-2.5 px-4">
          <div className="w-7 h-7 rounded-md bg-green-500/20 flex items-center justify-center">
            <Database className="w-4 h-4 text-green-400" />
          </div>
          <div>
            <div className="text-sm font-semibold leading-none">Bagger</div>
            <div className="text-[10px] text-muted-foreground leading-tight mt-0.5">
              Memory Browser
            </div>
          </div>
        </div>

        <Separator />

        {/* Navigation */}
        <nav className="flex-1 p-2 space-y-0.5">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors",
                  isActive
                    ? "bg-green-500/10 text-green-400 font-medium"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50 cursor-pointer",
                )
              }
            >
              <item.icon className="w-4 h-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <Separator />

        {/* Status */}
        <div className="px-4 py-3 text-xs text-muted-foreground">
          {health ? (
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "w-1.5 h-1.5 rounded-full shrink-0",
                  health.status === "ok" ? "bg-green-500" : "bg-yellow-500",
                )}
              />
              <span>{health.sessions_count} sessions</span>
              <span className="ml-auto font-mono text-[10px] opacity-50">
                v{health.version}
              </span>
            </div>
          ) : (
            <div className="h-3 w-full bg-muted rounded animate-pulse" />
          )}
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
