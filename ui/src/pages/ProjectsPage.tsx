import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Folder, FolderOpen, ChevronRight, AlertCircle } from "lucide-react";
import { getSessions, type Session } from "@/lib/api";
import { cn, formatDateShort } from "@/lib/utils";
import { EmptyState } from "@/components/EmptyState";

function basename(p: string): string {
  if (!p || p === "no-project") return "Unknown project";
  const normalized = p.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  return parts[parts.length - 1] || p;
}

interface ProjectGroup {
  path: string;
  name: string;
  sessions: Session[];
  last: string;
}

export default function ProjectsPage() {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const { data, isLoading, error } = useQuery({
    queryKey: ["projects-all"],
    queryFn: async () => {
      // Backend caps per_page at 200 (sessions.py), so paginate to fetch all.
      const all: Session[] = [];
      let page = 1;
      const perPage = 200;
      for (;;) {
        const res = await getSessions(page, perPage, "last_message_at", "desc");
        all.push(...res.data);
        if (res.data.length === 0 || all.length >= res.meta.total) break;
        page++;
      }
      return {
        data: all,
        meta: { total: all.length, page: 1, per_page: all.length, pages: 1 },
      };
    },
  });

  const projects: ProjectGroup[] = (() => {
    const map = new Map<string, ProjectGroup>();
    (data?.data ?? []).forEach((s) => {
      const path = s.project_path || "no-project";
      const entry =
        map.get(path) ??
        ({
          path,
          name: basename(path) || "Unknown project",
          sessions: [],
          last: s.last_message_at,
        } as ProjectGroup);
      entry.sessions.push(s);
      if (s.last_message_at > entry.last) entry.last = s.last_message_at;
      map.set(path, entry);
    });
    return [...map.values()]
      .sort((a, b) => {
        const aUnknown = a.path === "no-project" ? 1 : 0;
        const bUnknown = b.path === "no-project" ? 1 : 0;
        if (aUnknown !== bUnknown) return aUnknown - bUnknown; // unknowns sink to bottom
        return b.last.localeCompare(a.last);
      })
      .map((p) => ({
        ...p,
        sessions: [...p.sessions].sort((a, b) =>
          b.last_message_at.localeCompare(a.last_message_at),
        ),
      }));
  })();

  const totalSessions = data?.meta.total ?? 0;

  const toggle = (path: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  return (
    <div className="max-w-5xl mx-auto space-y-8 animate-fade-in-up">
      {/* Header */}
      <header className="space-y-2">
        <h1 className="font-display text-3xl font-medium tracking-tight text-foreground">
          Projects
        </h1>
        <p className="text-sm text-muted-foreground">
          Your coding memory, organized by repository.
          {projects.length > 0 && (
            <span className="ml-2 font-mono text-tertiary">
              {projects.length} project{projects.length !== 1 ? "s" : ""} ·{" "}
              {totalSessions} session{totalSessions !== 1 ? "s" : ""}
            </span>
          )}
        </p>
      </header>

      {/* Content */}
      {error ? (
        <div className="flex flex-col items-center py-20 text-muted-foreground">
          <AlertCircle className="w-10 h-10 mb-4 text-warning/60" />
          <p className="text-sm">Failed to load projects</p>
          <p className="text-xs mt-2 opacity-50 font-mono">
            {(error as Error).message}
          </p>
        </div>
      ) : isLoading ? (
        <div className="rounded-card overflow-hidden border border-[var(--border-subtle)]">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="px-2 py-4 h-16 border-b border-[var(--border-subtle)] last:border-0 animate-pulse"
            />
          ))}
        </div>
      ) : projects.length === 0 ? (
        <EmptyState
          icon={Folder}
          title="No projects yet"
          description={
            <span>
              Run{" "}
              <code className="text-success bg-success/8 px-1.5 py-0.5 rounded border border-success/15">
                bagger scan
              </code>{" "}
              to import sessions
            </span>
          }
        />
      ) : (
        <ul className="rounded-card overflow-hidden border border-[var(--border-subtle)]">
          {projects.map((p) => {
            const isOpen = expanded.has(p.path);
            return (
              <li
                key={p.path}
                className="border-b border-[var(--border-subtle)] last:border-0"
              >
                <button
                  onClick={() => toggle(p.path)}
                  className="group w-full flex items-center gap-3 px-2 py-4 text-left transition-colors duration-200 hover:bg-[var(--brand-bg)]"
                  aria-expanded={isOpen}
                >
                  {isOpen ? (
                    <FolderOpen
                      className="w-[18px] h-[18px] shrink-0 text-[var(--brand-500)]"
                      strokeWidth={1.5}
                    />
                  ) : (
                    <Folder
                      className="w-[18px] h-[18px] shrink-0 text-muted-foreground group-hover:text-foreground"
                      strokeWidth={1.5}
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground truncate">
                      {p.name}
                    </p>
                    <p className="text-xs text-muted-foreground font-mono truncate mt-0.5">
                      {p.path === "no-project" ? "No project path" : p.path}
                    </p>
                  </div>
                  <span className="text-[11px] font-mono text-tertiary shrink-0">
                    {p.sessions.length}
                  </span>
                  <span className="text-xs text-muted-foreground font-mono shrink-0 hidden sm:block">
                    {formatDateShort(p.last)}
                  </span>
                  <ChevronRight
                    className={cn(
                      "w-4 h-4 shrink-0 text-muted-foreground transition-transform duration-200",
                      isOpen && "rotate-90",
                    )}
                  />
                </button>

                {isOpen && (
                  <div className="pb-3 pl-9 pr-2 space-y-0.5">
                    {p.sessions.slice(0, 5).map((s) => (
                      <Link
                        key={s.id}
                        to={`/sessions/${s.id}`}
                        className="group flex items-center gap-2 py-1.5 rounded-md px-2 hover:bg-muted/40 transition-colors duration-200"
                      >
                        <span className="flex-1 min-w-0 truncate text-xs text-muted-foreground group-hover:text-foreground">
                          {s.summary || "Untitled Session"}
                        </span>
                        <span className="text-[10px] font-mono text-tertiary shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                          {formatDateShort(s.last_message_at)}
                        </span>
                      </Link>
                    ))}
                    <Link
                      to={`/sessions?project=${encodeURIComponent(p.path)}`}
                      className="mt-1 flex items-center gap-1 px-2 py-1.5 text-xs text-[var(--brand-500)] hover:underline transition-colors duration-200"
                    >
                      View all {p.sessions.length} sessions
                      <ChevronRight className="w-3 h-3" />
                    </Link>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
