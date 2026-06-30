import { useRef, useEffect } from "react";
import MessageBubble from "./MessageBubble";
import type { Event } from "@/lib/api";

interface ConversationViewProps {
  events: Event[];
}

export default function ConversationView({ events }: ConversationViewProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new events load
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  return (
    <div className="space-y-6 pb-4">
      {events.map((event) => (
        <div key={event.event_id} id={`msg-${event.event_id}`}>
          <MessageBubble event={event} />
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
