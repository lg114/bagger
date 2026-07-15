import { useState, useMemo } from "react";
import {
  NavLink,
  Outlet,
  useNavigate,
  useSearchParams,
  Link,
} from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { type Window, getCurrentWindow } from "@tauri-apps/api/window";
import {
  Home,
  Search,
  BarChart3,
  RefreshCw,
  Settings,
  Folder,
  FolderOpen,
} from "lucide-react";
import { cn, formatDateShort } from "@/lib/utils";
import { getSessions, type Session } from "@/lib/api";
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

function basename(p: string): string {
  const parts = p.split("/").filter(Boolean);
  return parts[parts.length - 1] || p;
}

const viewItems = [
  { to: "/", icon: Home, label: "Dashboard" },
  { to: "/stats", icon: BarChart3, label: "Analytics" },
  { to: "/import", icon: RefreshCw, label: "Scan" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

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

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const activeProject = searchParams.get("project");

  // Pull a wide slice of sessions once to build the project map.
  const { data } = useQuery({
    queryKey: ["sidebar-projects"],
    queryFn: () => getSessions(1, 200),
  });

  const projects = useMemo(() => {
    const map = new Map<
      string,
      { path: string; name: string; sessions: Session[]; last: string }
    >();
    (data?.data ?? []).forEach((s) => {
      const entry =
        map.get(s.project_path) ??
        ({ path: s.project_path, name: basename(s.project_path), sessions: [], last: s.last_message_at } as {
          path: string;
          name: string;
          sessions: Session[];
          last: string;
        });
      entry.sessions.push(s);
      if (s.last_message_at > entry.last) entry.last = s.last_message_at;
      map.set(s.project_path, entry);
    });
    return [...map.values()]
      .sort((a, b) => b.last.localeCompare(a.last))
      .slice(0, 6)
      .map((p) => ({
        ...p,
        sessions: [...p.sessions]
          .sort((a, b) => b.last_message_at.localeCompare(a.last_message_at))
          .slice(0, 3),
      }));
  }, [data]);

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

          {sidebarOpen ? (
            <>
              {/* Persistent search — the front door */}
              <div className="px-3 pb-3">
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const v = q.trim();
                    if (v) navigate(`/search?q=${encodeURIComponent(v)}`);
                  }}
                >
                  <div className="flex items-center gap-2 rounded-md border border-[var(--border-subtle)] bg-[var(--bg-input)] px-2.5 py-2 transition-colors focus-within:border-[var(--brand-500)]">
                    <Search className="w-4 h-4 text-muted-foreground shrink-0" strokeWidth={1.5} />
                    <input
                      value={q}
                      onChange={(e) => setQ(e.target.value)}
                      placeholder="Search memory…"
                      className="flex-1 min-w-0 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none"
                    />
                    <kbd className="text-[10px] font-mono text-tertiary border border-[var(--border-subtle)] rounded px-1.5 py-0.5 shrink-0">
                      ⌘K
                    </kbd>
                  </div>
                </form>
              </div>

              {/* Scrollable body: Projects map + Views */}
              <div className="flex-1 min-h-0 overflow-y-auto px-2.5 py-1 space-y-5">
                {/* Projects — the memory map */}
                <div>
                  <p className="text-[11px] uppercase tracking-wider text-tertiary px-2 mb-1.5 font-medium">
                    Projects
                  </p>
                  <div className="space-y-0.5">
                    {projects.length === 0 && (
                      <p className="text-xs text-muted-foreground px-2 py-1">
                        No sessions yet
                      </p>
                    )}
                    {projects.map((p) => {
                      const isOpen = expanded === p.path || activeProject === p.path;
                      const isActive = activeProject === p.path;
                      return (
                        <div key={p.path}>
                          <button
                            onClick={() => setExpanded(isOpen ? null : p.path)}
                            className={cn(
                              "relative w-full flex items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors duration-200",
                              isActive
                                ? "text-[var(--brand-500)]"
                                : "text-muted-foreground hover:text-foreground hover:bg-muted/40",
                            )}
                          >
                            {isActive && (
                              <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-[var(--brand-500)]" />
                            )}
                            {isOpen ? (
                              <FolderOpen className="w-[18px] h-[18px] shrink-0" strokeWidth={1.5} />
                            ) : (
                              <Folder className="w-[18px] h-[18px] shrink-0" strokeWidth={1.5} />
                            )}
                            <span className="flex-1 min-w-0 truncate text-sm font-medium">
                              {p.name}
                            </span>
                            <span className="text-[11px] font-mono text-tertiary shrink-0">
                              {p.sessions.length}
                            </span>
                          </button>
                          {isOpen && (
                            <div className="mt-0.5 pb-1 space-y-0.5">
                              {p.sessions.map((s) => (
                                <Link
                                  key={s.id}
                                  to={`/sessions/${s.id}`}
                                  className="group flex items-center gap-2 pl-9 pr-2 py-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors duration-200"
                                >
                                  <span className="flex-1 min-w-0 truncate text-xs">
                                    {s.summary || "Untitled session"}
                                  </span>
                                  <span className="text-[10px] font-mono text-tertiary shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                                    {formatDateShort(s.last_message_at)}
                                  </span>
                                </Link>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Views — demoted to secondary */}
                <div>
                  <p className="text-[11px] uppercase tracking-wider text-tertiary px-2 mb-1.5 font-medium">
                    Views
                  </p>
                  <nav className="space-y-0.5">
                    {viewItems.map((item) => (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        end={item.to === "/"}
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
                            <item.icon className="w-[18px] h-[18px] shrink-0" strokeWidth={1.5} />
                            <span className="flex-1 truncate text-sm font-medium">{item.label}</span>
                          </>
                        )}
                      </NavLink>
                    ))}
                  </nav>
                </div>
              </div>

              {/* Footer — sync status */}
              <div className="shrink-0 border-t border-[var(--border-subtle)] px-3 py-2.5">
                <Link
                  to="/settings"
                  className="flex items-center gap-2 text-[11px] text-tertiary hover:text-foreground transition-colors duration-200"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--success)] shrink-0" />
                  <span className="font-mono">Synced</span>
                </Link>
              </div>
            </>
          ) : (
            /* Collapsed: icon spine */
            <>
              <div className="flex-1 min-h-0 overflow-y-auto py-2 space-y-1 flex flex-col items-center">
                <button
                  onClick={() => navigate("/search")}
                  className="p-2 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors duration-200"
                  title="Search"
                >
                  <Search className="w-[18px] h-[18px]" strokeWidth={1.5} />
                </button>
                {viewItems.map((item) => (
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
              <div className="shrink-0 border-t border-[var(--border-subtle)] py-2.5 flex justify-center">
                <Link to="/settings" title="Synced">
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--success)]" />
                </Link>
              </div>
            </>
          )}
        </aside>

        {/* ── Right column: Title strip + Content ── */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0 bg-base">
          <div className="titlebar-drag h-14 shrink-0 flex items-center justify-end px-4">
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
