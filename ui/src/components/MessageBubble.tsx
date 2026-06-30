import { User, Bot } from "lucide-react";
import ContentBlockRenderer from "./ContentBlock";
import type { Event } from "@/lib/api";

interface MessageBubbleProps {
  event: Event;
}

export default function MessageBubble({ event }: MessageBubbleProps) {
  const isUser = event.role === "user";

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      {/* Avatar */}
      <div
        className={`w-7 h-7 rounded-md flex items-center justify-center shrink-0 mt-0.5 ${
          isUser
            ? "bg-sky-500/20 text-sky-400"
            : "bg-violet-500/20 text-violet-400"
        }`}
      >
        {isUser ? (
          <User className="w-3.5 h-3.5" />
        ) : (
          <Bot className="w-3.5 h-3.5" />
        )}
      </div>

      {/* Bubble */}
      <div
        className={`max-w-[80%] min-w-0 ${
          isUser ? "items-end" : ""
        }`}
      >
        <div
          className={`rounded-lg px-4 py-3 ${
            isUser
              ? "bg-sky-500/10 border border-sky-500/20 rounded-tr-sm"
              : "bg-card border border-border rounded-tl-sm"
          }`}
        >
          {/* Content blocks */}
          {event.content_blocks?.length > 0 ? (
            <div className="space-y-2">
              {event.content_blocks.map((block, i) => (
                <ContentBlockRenderer key={i} block={block} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground italic">Empty message</p>
          )}
        </div>

        {/* Metadata footer */}
        <div
          className={`flex items-center gap-2 mt-1 text-[10px] text-muted-foreground ${
            isUser ? "justify-end" : ""
          }`}
        >
          <span className="font-mono">
            {event.timestamp?.slice(11, 19) || ""}
          </span>
          {event.model && (
            <span className="opacity-50">{event.model}</span>
          )}
          {(event.token_input > 0 || event.token_output > 0) && (
            <span className="opacity-50 tabular-nums">
              {event.token_input + event.token_output} tok
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
