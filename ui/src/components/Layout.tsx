import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  Home,
  MessageSquare,
  Search,
  BarChart3,
  RefreshCw,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import StatusBar from "./StatusBar";

const navItems = [
  { to: "/", icon: Home, label: "Dashboard" },
  { to: "/sessions", icon: MessageSquare, label: "Conversations" },
  { to: "/search", icon: Search, label: "Search" },
  { to: "/stats", icon: BarChart3, label: "Analytics" },
  { to: "/import", icon: RefreshCw, label: "Scan" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="flex flex-row h-screen">
      {/* ── Left column: Sidebar ── */}
      <aside
        className={cn(
          "shrink-0 flex flex-col bg-surface h-full transition-all duration-200 ease-apple",
          sidebarOpen ? "w-[220px]" : "w-10",
        )}
      >
        {/* Sidebar header — bagger logo toggle */}
        <div
          className={cn(
            "h-12 shrink-0 flex items-center transition-all duration-200",
            sidebarOpen ? "px-4" : "justify-center",
          )}
        >
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1.5 rounded-element text-muted-foreground hover:text-foreground hover:bg-muted transition-colors duration-200 focus:outline-none shrink-0"
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
        </div>

        {/* Navigation */}
        <nav
          className={cn(
            "flex-1 space-y-1 overflow-hidden transition-all duration-200",
            sidebarOpen ? "p-3" : "px-0.5 py-3",
          )}
        >
          {navItems.map((item, idx) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center rounded-element text-sm transition-all duration-200 ease-out whitespace-nowrap",
                  sidebarOpen
                    ? "gap-2.5 px-3 py-2"
                    : "justify-center py-2",
                  idx === 4 && sidebarOpen ? "mt-3" : "",
                  isActive
                    ? "bg-primary/10 text-[var(--nav-active-text)] font-medium border border-[var(--nav-active-border)]"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted border border-transparent",
                )
              }
            >
              <item.icon className="w-[18px] h-[18px] shrink-0" />
              {sidebarOpen && <span className="flex-1 truncate">{item.label}</span>}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* ── Right column: Content + StatusBar ── */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        <main className="flex-1 overflow-y-auto">
          <div className="px-12 py-10 min-h-full">
            <Outlet />
          </div>
        </main>
        <StatusBar />
      </div>
    </div>
  );
}
