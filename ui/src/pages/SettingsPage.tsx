import { Settings, RefreshCw, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function SettingsPage() {
  return (
    <div className="max-w-3xl mx-auto space-y-8 animate-fade-in-up">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight mb-2">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Configure database, shortcuts, and preferences
        </p>
      </div>

      {/* About / Version */}
      <section className="glass-card-static p-6 space-y-4">
        <h2 className="text-sm font-semibold tracking-tight flex items-center gap-2">
          <Settings className="w-4 h-4 text-primary/60" />
          About
        </h2>

        <div className="space-y-3">
          <div className="flex items-center justify-between py-2">
            <div>
              <p className="text-sm">Bagger</p>
              <p className="text-xs text-muted-foreground font-mono">Memory Browser for Claude Code</p>
            </div>
            <span className="text-sm font-mono font-semibold">v0.2.0</span>
          </div>

          <div className="h-px bg-border" />

          <div className="flex items-center justify-between py-2">
            <div>
              <p className="text-sm">Check for updates</p>
              <p className="text-xs text-muted-foreground">You're running the latest version</p>
            </div>
            <Button variant="outline" size="sm" className="border-primary/15 hover:border-primary/35 hover:bg-primary/10 hover:text-primary">
              <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
              Check
            </Button>
          </div>

          <div className="h-px bg-border" />

          <a
            href="https://github.com"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-between py-2 hover:bg-muted/50 rounded-element px-2 -mx-2 transition-colors duration-200"
          >
            <div>
              <p className="text-sm">GitHub</p>
              <p className="text-xs text-muted-foreground">Source code and issues</p>
            </div>
            <ExternalLink className="w-3.5 h-3.5 text-muted-foreground" />
          </a>
        </div>
      </section>

      {/* Coming soon sections */}
      <section className="glass-card-static p-6 space-y-3">
        <h2 className="text-sm font-semibold tracking-tight flex items-center gap-2">
          <Settings className="w-4 h-4 text-primary/60" />
          General
        </h2>
        <p className="text-sm text-muted-foreground">
          Language, startup watch, and keyboard shortcuts — coming soon.
        </p>
      </section>

      <section className="glass-card-static p-6 space-y-3">
        <h2 className="text-sm font-semibold tracking-tight flex items-center gap-2">
          <Settings className="w-4 h-4 text-primary/60" />
          Database
        </h2>
        <p className="text-sm text-muted-foreground">
          DB path, backup/restore, FTS5 rebuild, storage usage — coming soon.
        </p>
      </section>
    </div>
  );
}
