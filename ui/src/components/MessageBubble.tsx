import { User, Bot } from "lucide-react";
import ContentBlockRenderer from "./ContentBlock";
import type { Event } from "@/lib/api";

interface MessageBubbleProps {
  event: Event;
}

export default function MessageBubble({ event }: MessageBubbleProps) {
  const isUser = event.role === "user";

  return (
    <div className={`flex gap-4 ${isUser ? "flex-row-reverse" : ""}`}>
      {/* Avatar */}
      <div
        className={`w-9 h-9 rounded-element flex items-center justify-center shrink-0 mt-0.5 border transition-colors duration-300 ease-apple ${
          isUser
            ? "bg-primary/10 text-primary border-primary/15"
            : "bg-info/10 text-info border-info/15"
        }`}
      >
        {isUser ? (
          <User className="w-[16px] h-[16px]" />
        ) : (
          <Bot className="w-[16px] h-[16px]" />
        )}
      </div>

      {/* Bubble */}
      <div
        className={`max-w-[80%] min-w-0 ${isUser ? "items-end" : ""}`}
      >
        <div
          className={`rounded-card px-5 py-4 transition-colors duration-300 ease-apple ${
            isUser
              ? "bg-primary/10 border border-primary/15 rounded-tr-element"
              : "glass-card-static rounded-tl-element"
          }`}
        >
          {/* Content blocks */}
          {event.content_blocks?.length > 0 ? (
            <div className="space-y-3">
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
          className={`flex items-center gap-2 mt-2 text-[10px] text-muted-foreground font-mono ${
            isUser ? "justify-end" : ""
          }`}
        >
          <span className="tabular-nums opacity-50">
            {event.timestamp?.slice(11, 19) || ""}
          </span>
          {event.model && (
            <span className="opacity-30">{event.model}</span>
          )}
          {(event.token_input > 0 || event.token_output > 0) && (
            <span className="opacity-30 tabular-nums">
              {event.token_input + event.token_output} tok
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
