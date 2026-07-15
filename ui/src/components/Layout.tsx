import { useState, useCallback } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { type Window, getCurrentWindow } from "@tauri-apps/api/window";
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

let cachedWin: Window | null | undefined;
function getWin(): Window | null {
  if (cachedWin !== undefined) return cachedWin;
  try {
    cachedWin = getCurrentWindow();
  } catch {
    cachedWin = null;
  }
  return cachedWin;
}

const navItems = [
  { to: "/", icon: Home, label: "Dashboard" },
  { to: "/sessions", icon: MessageSquare, label: "Conversations" },
  { to: "/search", icon: Search, label: "Search" },
  { to: "/stats", icon: BarChart3, label: "Analytics" },
  { to: "/import", icon: RefreshCw, label: "Scan" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

function WindowControls() {
  const win = getWin();

  const minimize = useCallback(() => win?.minimize(), []);
  const toggleMax = useCallback(() => win?.toggleMaximize(), []);
  const close = useCallback(() => win?.close(), []);

  if (!win) return null;

  const noDrag = { WebkitAppRegion: "no-drag" } as React.CSSProperties;

  return (
    <div className="flex items-center gap-1" style={noDrag}>
      {/* Minimize */}
      <button
        onClick={minimize}
        className="p-1.5 rounded-element text-muted-foreground hover:text-foreground hover:bg-muted transition-colors duration-200 focus:outline-none"
        title="最小化"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M2 6.5h8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
      </button>

      {/* Maximize */}
      <button
        onClick={toggleMax}
        className="p-1.5 rounded-element text-muted-foreground hover:text-foreground hover:bg-muted transition-colors duration-200 focus:outline-none"
        title="最大化"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <rect x="2" y="2" width="8" height="8" rx="1" stroke="currentColor" strokeWidth="1.2" />
        </svg>
      </button>

      {/* Close */}
      <button
        onClick={close}
        className="p-1.5 rounded-element text-muted-foreground hover:text-white hover:bg-[var(--error)] transition-colors duration-200 focus:outline-none"
        title="关闭"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  );
}

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="flex flex-col h-screen">
      <div className="flex flex-row flex-1 min-h-0">
        {/* ── Left column: Sidebar (editorial spine) ── */}
        <aside
          className={cn(
            "shrink-0 flex flex-col h-full bg-base border-r border-[var(--border-subtle)] transition-all duration-200 ease-apple",
            sidebarOpen ? "w-56" : "w-14",
          )}
        >
          {/* Sidebar header — wordmark + drag region + toggle */}
          <div
            className={cn(
              "titlebar-drag h-14 shrink-0 flex items-center border-b border-[var(--border-subtle)] transition-all duration-200",
              sidebarOpen ? "px-4 justify-between" : "justify-center px-2",
            )}
          >
            {sidebarOpen ? (
              <span className="font-display text-lg tracking-tight text-foreground select-none">
                bagger
              </span>
            ) : (
              <span className="font-display text-lg tracking-tight text-[var(--brand-500)] select-none">
                b
              </span>
            )}
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="p-1.5 rounded-element text-muted-foreground hover:text-foreground hover:bg-muted transition-colors duration-200 focus:outline-none shrink-0"
              style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
              title={sidebarOpen ? "折叠侧栏" : "展开侧栏"}
            >
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
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
          <nav className="flex-1 py-4 px-2.5 space-y-0.5 overflow-hidden">
            {navItems.map((item, idx) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  cn(
                    "relative flex items-center rounded-md transition-colors duration-200 ease-out whitespace-nowrap",
                    sidebarOpen ? "gap-3 px-3 py-2" : "justify-center px-2 py-2.5",
                    idx === 4 && sidebarOpen ? "mt-4" : "",
                    isActive
                      ? "text-[var(--brand-500)]"
                      : "text-muted-foreground hover:text-foreground",
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive && (
                      <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-[var(--brand-500)]" />
                    )}
                    <item.icon
                      className="w-[18px] h-[18px] shrink-0"
                      strokeWidth={1.5}
                    />
                    {sidebarOpen && (
                      <span className="flex-1 truncate text-sm font-medium">
                        {item.label}
                      </span>
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </aside>

        {/* ── Right column: Title strip + Content ── */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0 bg-base">
          {/* Title bar strip — drag region + window controls */}
          <div className="titlebar-drag h-14 shrink-0 flex items-center justify-end px-4 border-b border-[var(--border-subtle)]">
            <WindowControls />
          </div>

          <main className="flex-1 overflow-y-auto">
            <div className="px-12 py-10 min-h-full">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
      <StatusBar />
    </div>
  );
}
