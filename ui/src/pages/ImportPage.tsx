import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw, CheckCircle, Clock } from "lucide-react";
import { triggerScan } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export default function ImportPage() {
  const queryClient = useQueryClient();
  const [scanning, setScanning] = useState(false);
  const [lastResult, setLastResult] = useState<{ sessions: number; events: number; skipped: number } | null>(null);

  const handleScan = async () => {
    setScanning(true);
    try {
      const result = await triggerScan();
      setLastResult(result);
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
    } catch {
      // Error handled by React Query
    } finally {
      setScanning(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-8 animate-fade-in-up">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight mb-2">Scan</h1>
        <p className="text-sm text-muted-foreground">
          Scan Claude Code JSONL sessions from ~/.claude/projects
        </p>
      </div>

      {/* Scan card */}
      <div className="glass-card-static p-8 space-y-5">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-element bg-primary/10 flex items-center justify-center border border-primary/15 shrink-0">
            <RefreshCw className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h2 className="text-sm font-semibold">Scan for sessions</h2>
            <p className="text-xs text-muted-foreground mt-1">
              Searches ~/.claude/projects for JSONL files and imports new conversations.
            </p>
          </div>
        </div>

        <Button
          variant="outline"
          size="sm"
          onClick={handleScan}
          disabled={scanning}
          className="w-full justify-center border-primary/15 hover:border-primary/35 hover:bg-primary/10 hover:text-primary transition-all duration-200"
        >
          <RefreshCw className={cn("w-3.5 h-3.5 mr-1.5", scanning && "animate-spin")} />
          {scanning ? "Scanning..." : "Start Scan"}
        </Button>
      </div>

      {/* Last scan result */}
      {lastResult && (
        <div className="glass-card-static p-8 space-y-4 animate-fade-in-up">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-success" />
            Last Scan Complete
          </h3>
          <div className="grid grid-cols-3 gap-4">
            <div className="text-center">
              <p className="text-2xl font-bold font-mono text-primary">{lastResult.sessions}</p>
              <p className="text-[11px] text-muted-foreground mt-1">Sessions</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold font-mono text-success">{lastResult.events}</p>
              <p className="text-[11px] text-muted-foreground mt-1">New Events</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold font-mono text-muted-foreground">{lastResult.skipped}</p>
              <p className="text-[11px] text-muted-foreground mt-1">Skipped</p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground font-mono">
            <Clock className="w-3 h-3" />
            Source: ~/.claude/projects/*.jsonl
          </div>
        </div>
      )}
    </div>
  );
}
