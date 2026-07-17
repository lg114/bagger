import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  RefreshCw,
  CheckCircle,
  FolderOpen,
  Activity,
  SkipForward,
  AlertCircle,
  Info,
} from "lucide-react";
import { triggerScan, triggerFullScan } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { MetricCard } from "@/components/MetricCard";

type ScanResult = { status: string; sessions: number; events: number; skipped: number };

export default function ImportPage() {
  const queryClient = useQueryClient();
  const [scanning, setScanning] = useState(false);
  const [mode, setMode] = useState<"incremental" | "full" | null>(null);
  const [lastResult, setLastResult] = useState<ScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runScan = async (kind: "incremental" | "full") => {
    setScanning(true);
    setMode(kind);
    setError(null);
    try {
      const result =
        kind === "incremental" ? await triggerScan() : await triggerFullScan();
      setLastResult(result);
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setScanning(false);
      setMode(null);
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-10 animate-fade-in-up">
      {/* Page header */}
      <header className="pt-2 space-y-2">
        <h1 className="font-display text-3xl font-medium tracking-tight text-foreground">
          Scan
        </h1>
        <p className="text-sm text-muted-foreground font-mono">
          Index Claude Code sessions into your local archive
        </p>
      </header>

      {/* Scan console */}
      <section className="glass-card-static p-6 sm:p-8 space-y-6">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-element bg-[var(--brand-bg)] flex items-center justify-center border border-[var(--brand-500)]/15 shrink-0">
            <RefreshCw className="w-5 h-5 text-[var(--brand-500)]" />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-foreground">Sync source</h2>
            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
              Imports new transcripts from{" "}
              <span className="font-mono text-foreground/70">
                ~/.claude/projects/*.jsonl
              </span>{" "}
              and parses them into searchable sessions.
            </p>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row gap-3">
          <Button
            size="lg"
            onClick={() => runScan("incremental")}
            disabled={scanning}
            className="flex-1 justify-center"
          >
            <RefreshCw
              className={cn(
                "w-4 h-4 mr-1.5",
                scanning && mode === "incremental" && "animate-spin",
              )}
            />
            {scanning && mode === "incremental" ? "Scanning..." : "Start Scan"}
          </Button>
          <Button
            variant="outline"
            size="lg"
            onClick={() => runScan("full")}
            disabled={scanning}
            className="flex-1 justify-center sm:flex-none sm:px-6"
          >
            <RefreshCw
              className={cn(
                "w-4 h-4 mr-1.5",
                scanning && mode === "full" && "animate-spin",
              )}
            />
            {scanning && mode === "full" ? "Rescanning..." : "Full Rescan"}
          </Button>
        </div>
      </section>

      {/* Last scan result */}
      {lastResult && !error && (
        <section className="space-y-4 animate-fade-in-up">
          <h2 className="font-display text-xl font-medium tracking-tight text-foreground flex items-center gap-2.5">
            <CheckCircle className="w-4 h-4 text-[var(--success)]" />
            Last Scan
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <MetricCard
              label="Sessions"
              value={lastResult.sessions}
              color="var(--brand-500)"
              icon={FolderOpen}
            />
            <MetricCard
              label="New Events"
              value={lastResult.events}
              color="var(--success)"
              icon={Activity}
            />
            <MetricCard
              label="Skipped"
              value={lastResult.skipped}
              color="var(--text-tertiary)"
              icon={SkipForward}
            />
          </div>
        </section>
      )}

      {/* Error block */}
      {error && (
        <div className="flex items-center gap-2 text-sm text-[var(--error)] glass-card-static p-4 animate-fade-in-up">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span className="font-mono">{error}</span>
        </div>
      )}

      {/* Source note */}
      <section className="flex items-start gap-2.5 text-[11px] text-muted-foreground font-mono leading-relaxed glass-card-static p-4">
        <Info className="w-3.5 h-3.5 shrink-0 mt-0.5 text-muted-foreground/50" />
        <p>
          <span className="text-foreground/70">Start Scan</span> adds only new or
          changed sessions.{" "}
          <span className="text-foreground/70">Full Rescan</span> re-parses every
          transcript from disk. Source:{" "}
          <span className="text-foreground/70">~/.claude/projects/*.jsonl</span>
        </p>
      </section>
    </div>
  );
}
