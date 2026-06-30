import { useState } from "react";
import { ChevronDown, ChevronRight, Wrench, Brain, FileOutput } from "lucide-react";
import type { ContentBlock as ContentBlockType } from "@/lib/api";

interface Props {
  block: ContentBlockType;
}

export default function ContentBlockRenderer({ block }: Props) {
  switch (block.block_type) {
    case "text":
      return <TextBlock text={block.text || ""} />;
    case "thinking":
      return <ThinkingBlock text={block.text || ""} />;
    case "tool_use":
      return <ToolUseBlock name={block.tool_name || "unknown"} input={block.tool_input} />;
    case "tool_result":
      return <ToolResultBlock text={block.text || ""} />;
    default:
      return <TextBlock text={JSON.stringify(block)} />;
  }
}

function TextBlock({ text }: { text: string }) {
  // Simple line-break rendering — react-markdown will be added later for code blocks
  return (
    <div className="text-sm leading-relaxed whitespace-pre-wrap break-words">
      {text}
    </div>
  );
}

function ThinkingBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="my-1">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5" />
        )}
        <Brain className="w-3.5 h-3.5" />
        <span>Thinking ({text.length} chars)</span>
      </button>
      {open && (
        <div className="mt-2 p-3 rounded-md bg-secondary/50 border border-border text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap break-words italic">
          {text}
        </div>
      )}
    </div>
  );
}

function ToolUseBlock({
  name,
  input,
}: {
  name: string;
  input?: Record<string, unknown>;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="my-1">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-xs font-medium text-green-400 hover:text-green-300 transition-colors cursor-pointer"
      >
        <Wrench className="w-3.5 h-3.5" />
        <span className="font-mono">Tool: {name}</span>
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 ml-auto" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 ml-auto" />
        )}
      </button>
      {open && input && (
        <pre className="mt-2 p-3 rounded-md bg-secondary/50 border border-border text-xs font-mono text-muted-foreground overflow-x-auto">
          {JSON.stringify(input, null, 2)}
        </pre>
      )}
    </div>
  );
}

function ToolResultBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const preview = text.slice(0, 200);

  return (
    <div className="my-1 pl-4 border-l-2 border-border">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer w-full text-left"
      >
        <FileOutput className="w-3.5 h-3.5" />
        <span className="truncate">
          Result{!open && text.length > 200 ? `: ${preview}…` : ""}
        </span>
      </button>
      {open && (
        <pre className="mt-2 p-3 rounded-md bg-secondary/30 text-xs font-mono text-muted-foreground leading-relaxed whitespace-pre-wrap break-words max-h-64 overflow-y-auto">
          {text}
        </pre>
      )}
    </div>
  );
}
