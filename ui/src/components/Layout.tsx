import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { type Window, getCurrentWindow } from "@tauri-apps/api/window";
import {
  Home,
  Search,
  MessagesSquare,
  RefreshCw,
  type LucideIcon,
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

// MVP nav: scan → search → view sessions. Memories / Stats / Projects /
// Settings are intentionally hidden (out of MVP scope).
const navItems = {
  browse: [
    { to: "/", icon: Home, label: "Home" },
    { to: "/search", icon: Search, label: "Search" },
    { to: "/sessions", icon: MessagesSquare, label: "Sessions" },
    { to: "/import", icon: RefreshCw, label: "Scan" },
  ],
} as const;

function WindowControls() {
  const win = getWin();

  const minimize = () => win?.minimize();
  const toggleMax = () => win?.toggleMaximize();
  const close = () => win?.close();

  if (!win) return null;

  const noDrag = { WebkitAppRegion: "no-drag" } as React.CSSProperties;

  return (
    <div className="flex items-center gap-1" style={noDrag}>
      <button
        onClick={minimize}
        className="p-1.5 rounded-element text-muted-foreground hover:text-foreground hover:bg-muted transition-colors duration-200 focus:outline-none"
        title="最小化"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M2 6.5h8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
      </button>
      <button
        onClick={toggleMax}
        className="p-1.5 rounded-element text-muted-foreground hover:text-foreground hover:bg-muted transition-colors duration-200 focus:outline-none"
        title="最大化"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <rect x="2" y="2" width="8" height="8" rx="1" stroke="currentColor" strokeWidth="1.2" />
        </svg>
      </button>
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

function NavRow({ to, icon: Icon, label }: { to: string; icon: LucideIcon; label: string }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        cn(
          "relative flex items-center gap-2.5 rounded-md px-2 py-1.5 transition-colors duration-200",
          isActive
            ? "text-[var(--brand-500)]"
            : "text-muted-foreground hover:text-foreground hover:bg-muted/40",
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-[var(--brand-500)]" />
          )}
          <Icon className="w-[18px] h-[18px] shrink-0" strokeWidth={1.5} />
          <span className="flex-1 truncate text-sm font-medium">{label}</span>
        </>
      )}
    </NavLink>
  );
}

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="flex flex-col h-screen">
      <div className="flex flex-row flex-1 min-h-0">
        {/* ── Left column: Sidebar (Memory Spine v2) ── */}
        <aside
          className={cn(
            "shrink-0 flex flex-col h-full bg-base border-r border-[var(--border-subtle)] transition-all duration-200 ease-apple",
            sidebarOpen ? "w-72" : "w-14",
          )}
        >
          {/* Sidebar header — wordmark + drag region + toggle */}
          <div
            className={cn(
              "titlebar-drag h-14 shrink-0 flex items-center transition-all duration-200",
              sidebarOpen ? "px-4 justify-between" : "justify-center px-2",
            )}
          >
            {sidebarOpen && (
              <span className="font-display text-lg tracking-tight text-foreground select-none">
                bagger
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

          {sidebarOpen ? (
            /* Expanded: MVP nav (Home → Search → Sessions → Scan) */
            <div className="flex-1 min-h-0 overflow-y-auto px-2.5 py-1">
              <nav className="space-y-0.5">
                {navItems.browse.map((item) => (
                  <NavRow
                    key={item.to}
                    to={item.to}
                    icon={item.icon}
                    label={item.label}
                  />
                ))}
              </nav>
            </div>
          ) : (
            /* Collapsed: icon spine */
            <div className="flex-1 min-h-0 overflow-y-auto py-2 space-y-1 flex flex-col items-center">
              {navItems.browse.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  title={item.label}
                  className={({ isActive }) =>
                    cn(
                      "p-2 rounded-md transition-colors duration-200",
                      isActive
                        ? "text-[var(--brand-500)]"
                        : "text-muted-foreground hover:text-foreground hover:bg-muted/40",
                    )
                  }
                >
                  <item.icon className="w-[18px] h-[18px]" strokeWidth={1.5} />
                </NavLink>
              ))}
            </div>
          )}
        </aside>

        {/* ── Right column: Title strip + Content ── */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0 bg-base">
          <div className="titlebar-drag h-14 shrink-0 flex items-center justify-end px-4">
            <WindowControls />
          </div>

          <main className="flex-1 min-w-0 overflow-y-auto">
            <div className="px-5 py-6 md:px-8 md:py-8 lg:px-10 lg:py-10 xl:px-12 xl:py-10 min-h-full">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
      <StatusBar />
    </div>
  );
}
