import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Info, Database, ExternalLink, SlidersHorizontal, HardDrive } from "lucide-react";
import { getHealth } from "@/lib/api";

export default function SettingsPage() {
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: getHealth });
  const online = health?.status === "ok";

  return (
    <div className="max-w-3xl mx-auto space-y-10 animate-fade-in-up">
      {/* Page header */}
      <header className="pt-2 space-y-2">
        <h1 className="font-display text-3xl font-medium tracking-tight text-foreground">
          Settings
        </h1>
        <p className="text-sm text-muted-foreground font-mono">
          Preferences, archive, and about
        </p>
      </header>

      {/* About */}
      <section className="space-y-4">
        <h2 className="font-display text-xl font-medium tracking-tight text-foreground flex items-center gap-2.5">
          <Info className="w-4 h-4 text-muted-foreground/50" />
          About
        </h2>
        <div className="rounded-card overflow-hidden border border-[var(--border-subtle)]">
          <InfoRow
            label="Bagger"
            hint="Memory Browser for Claude Code"
            value={<span className="text-foreground/80">{health?.version ?? "—"}</span>}
          />
          <InfoRow
            label="Backend"
            value={
              <StatusDot
                ok={online}
                label={health ? (online ? "Connected" : health.status) : "Offline"}
              />
            }
          />
          <a
            href="https://github.com"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-between gap-4 px-5 py-3 border-b border-[var(--border-subtle)] last:border-0 hover:bg-[var(--brand-bg)] transition-colors duration-200"
          >
            <div className="min-w-0">
              <p className="text-sm text-foreground/90">GitHub</p>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono truncate">
                Source code and issues
              </p>
            </div>
            <ExternalLink className="w-4 h-4 text-muted-foreground/60 shrink-0" />
          </a>
        </div>
      </section>

      {/* Archive */}
      <section className="space-y-4">
        <h2 className="font-display text-xl font-medium tracking-tight text-foreground flex items-center gap-2.5">
          <Database className="w-4 h-4 text-muted-foreground/50" />
          Archive
        </h2>
        <div className="rounded-card overflow-hidden border border-[var(--border-subtle)]">
          <InfoRow
            label="Sessions"
            value={<span className="text-foreground/80">{(health?.sessions_count ?? 0).toLocaleString()}</span>}
          />
          <InfoRow
            label="Events"
            value={<span className="text-foreground/80">{(health?.events_count ?? 0).toLocaleString()}</span>}
          />
          <InfoRow
            label="Search index"
            value={
              <StatusDot
                ok={!!health?.fts_enabled}
                label={health?.fts_enabled ? "FTS5 enabled" : "Disabled"}
              />
            }
          />
          <InfoRow
            label="Source"
            hint="Watched transcript directory"
            value={
              <span className="text-foreground/70 text-xs truncate max-w-[14rem] sm:max-w-[18rem]">
                ~/.claude/projects/*.jsonl
              </span>
            }
          />
        </div>
      </section>

      {/* Placeholder sections */}
      <SectionPlaceholder
        icon={SlidersHorizontal}
        title="General"
        note="Language, startup watch, and keyboard shortcuts"
      />
      <SectionPlaceholder
        icon={HardDrive}
        title="Database"
        note="DB path, backup / restore, FTS5 rebuild, storage usage"
      />
    </div>
  );
}

function InfoRow({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-3 border-b border-[var(--border-subtle)] last:border-0">
      <div className="min-w-0">
        <p className="text-sm text-foreground/90">{label}</p>
        {hint && (
          <p className="text-xs text-muted-foreground mt-0.5 font-mono truncate">{hint}</p>
        )}
      </div>
      <div className="shrink-0 text-sm font-mono text-right">{value}</div>
    </div>
  );
}

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="w-1.5 h-1.5 rounded-full shrink-0"
        style={{ background: ok ? "var(--success)" : "var(--error)" }}
      />
      <span
        className="text-sm font-mono"
        style={{ color: ok ? "var(--success)" : "var(--error)" }}
      >
        {label}
      </span>
    </span>
  );
}

function SectionPlaceholder({
  icon: Icon,
  title,
  note,
}: {
  icon: typeof Info;
  title: string;
  note: string;
}) {
  return (
    <section className="space-y-4">
      <h2 className="font-display text-xl font-medium tracking-tight text-foreground flex items-center gap-2.5">
        <Icon className="w-4 h-4 text-muted-foreground/50" />
        {title}
        <span className="ml-auto text-[10px] uppercase tracking-[0.14em] text-muted-foreground font-mono border border-[var(--border-subtle)] rounded-full px-2 py-0.5">
          Coming soon
        </span>
      </h2>
      <div className="rounded-card overflow-hidden border border-[var(--border-subtle)] px-5 py-4">
        <p className="text-sm text-muted-foreground">{note} — coming soon.</p>
      </div>
    </section>
  );
}
