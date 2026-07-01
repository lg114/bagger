import { Download, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function ImportPage() {
  return (
    <div className="max-w-3xl mx-auto space-y-8 animate-fade-in-up">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight mb-2">Import</h1>
        <p className="text-sm text-muted-foreground">
          Manage Claude Code JSONL import and live watch
        </p>
      </div>

      <div className="glass-card-static p-8 space-y-4">
        <Download className="w-8 h-8 text-primary/40" />
        <h2 className="text-lg font-semibold">Coming Soon</h2>
        <p className="text-sm text-muted-foreground">
          Full import management, watch status, and scan controls will be available here.
        </p>
        <Button variant="outline" size="sm" className="mt-2">
          <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
          Scan Now
        </Button>
      </div>
    </div>
  );
}
