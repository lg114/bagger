import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { ChevronDown, ChevronRight, Wrench, Brain, FileOutput, Copy, Check } from "lucide-react";
import type { Components } from "react-markdown";
import type { ContentBlock as ContentBlockType } from "@/lib/api";

interface Props {
  block: ContentBlockType;
}

const markdownComponents: Components = {
  table: ({ children }) => (
    <div className="overflow-x-auto my-3">
      <table>{children}</table>
    </div>
  ),
};

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

// ── Markdown-powered text block ──

const TEXT_TRUNCATE_THRESHOLD = 150_000; // 150KB — render is slow beyond this

function TextBlock({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const isLarge = text.length > TEXT_TRUNCATE_THRESHOLD;

  if (isLarge && !expanded) {
    const preview = text.slice(0, 3000);
    const hiddenKB = Math.round((text.length - preview.length) / 1024);
    return (
      <div>
        <div className="markdown-content text-sm">
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={markdownComponents}>
            {preview}
          </ReactMarkdown>
        </div>
        <button
          onClick={() => setExpanded(true)}
          className="mt-2 text-xs font-mono text-primary hover:text-primary/70 transition-colors duration-200"
        >
          Show full message ({hiddenKB} KB hidden) &rarr;
        </button>
      </div>
    );
  }

  return (
    <div className="markdown-content text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={markdownComponents}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

// ── Thinking block (collapsible) ──

function ThinkingBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="my-1.5">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 text-xs text-muted-foreground hover:text-primary transition-colors duration-300 ease-apple cursor-pointer"
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5" />
        )}
        <Brain className="w-3.5 h-3.5 text-primary/50" />
        <span className="font-mono">Thinking ({text.length} chars)</span>
      </button>
      {open && (
        <div className="mt-2 p-4 rounded-element bg-secondary/40 border border-primary/10 text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap break-words italic">
          {text}
        </div>
      )}
    </div>
  );
}

// ── Tool use block (collapsible, JSON input) ──

function ToolUseBlock({
  name,
  input,
}: {
  name: string;
  input?: Record<string, unknown>;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="my-1.5">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 text-xs font-medium text-success hover:text-primary transition-colors duration-300 ease-apple cursor-pointer"
      >
        <Wrench className="w-3.5 h-3.5 text-success/70" />
        <span className="font-mono">Tool: {name}</span>
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 ml-auto" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 ml-auto" />
        )}
      </button>
      {open && input && (
        <div className="mt-2 p-4 rounded-element bg-secondary/40 border border-primary/10 text-xs font-mono text-muted-foreground overflow-x-auto">
          <JSONBlock value={input} />
        </div>
      )}
    </div>
  );
}

// ── Tool result block (collapsible) ──

function ToolResultBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const preview = text.slice(0, 200);

  return (
    <div className="my-1.5 pl-4 border-l-2 border-primary/15">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 text-xs text-muted-foreground hover:text-primary transition-colors duration-300 ease-apple cursor-pointer w-full text-left"
      >
        <FileOutput className="w-3.5 h-3.5 text-primary/40" />
        <span className="truncate font-mono">
          Result{!open && text.length > 200 ? `: ${preview}...` : ""}
        </span>
      </button>
      {open && (
        <div className="mt-2 p-4 rounded-element bg-secondary/30 text-xs font-mono text-muted-foreground leading-relaxed whitespace-pre-wrap break-words max-h-64 overflow-y-auto">
          {text}
        </div>
      )}
    </div>
  );
}

// ── Copyable JSON display ──

function JSONBlock({ value }: { value: Record<string, unknown> }) {
  const [copied, setCopied] = useState(false);
  const json = JSON.stringify(value, null, 2);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(json);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative group">
      <button
        onClick={handleCopy}
        className="absolute top-1 right-1 p-1.5 rounded-element bg-primary/10 hover:bg-primary/15 text-primary opacity-0 group-hover:opacity-100 transition-all duration-300 ease-apple"
        title="Copy JSON"
      >
        {copied ? <Check className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
      </button>
      <pre className="overflow-x-auto">{json}</pre>
    </div>
  );
}
