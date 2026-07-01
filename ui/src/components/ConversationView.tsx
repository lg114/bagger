import { useRef, useEffect, useState, useMemo } from "react";
import { ChevronDown } from "lucide-react";
import MessageBubble from "./MessageBubble";
import type { Event } from "@/lib/api";

const BATCH_SIZE = 50;

interface ConversationViewProps {
  events: Event[];
}

export default function ConversationView({ events }: ConversationViewProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [visibleCount, setVisibleCount] = useState(BATCH_SIZE);

  // When events change (new session loaded), reset to first batch
  const firstEventId = events[0]?.event_id;
  useEffect(() => {
    setVisibleCount(BATCH_SIZE);
  }, [firstEventId]);

  // Auto-scroll when loading more
  useEffect(() => {
    if (visibleCount > BATCH_SIZE) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [visibleCount]);

  // Scroll to bottom on initial mount (events loaded, first batch rendered)
  useEffect(() => {
    if (events.length > 0) {
      // Small delay to let the DOM render the first batch
      const timer = setTimeout(() => {
        bottomRef.current?.scrollIntoView({ behavior: "auto" });
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [firstEventId]);

  const visibleEvents = useMemo(
    () => events.slice(0, visibleCount),
    [events, visibleCount],
  );

  const remaining = events.length - visibleCount;

  const loadMore = () => {
    setVisibleCount((prev) => Math.min(prev + BATCH_SIZE, events.length));
  };

  const showAll = () => {
    setVisibleCount(events.length);
  };

  return (
    <div className="space-y-8 pb-6">
      {visibleEvents.map((event, i) => (
        <div key={event.event_id} id={`msg-${event.event_id}`} className="animate-fade-in-up" style={{ animationDelay: `${i * 30}ms` }}>
          <MessageBubble event={event} />
        </div>
      ))}

      {remaining > 0 && (
        <div className="flex items-center gap-3 py-4">
          <div className="flex-1 h-px bg-border" />
          <button
            onClick={loadMore}
            className="flex items-center gap-1.5 px-4 py-2 rounded-element border border-border text-xs font-mono text-muted-foreground hover:text-primary hover:border-primary/35 transition-all duration-200"
          >
            <ChevronDown className="w-3.5 h-3.5" />
            Show {Math.min(BATCH_SIZE, remaining)} more ({remaining} remaining)
          </button>
          <button
            onClick={showAll}
            className="text-xs font-mono text-muted-foreground hover:text-primary transition-colors duration-200"
          >
            All &darr;
          </button>
          <div className="flex-1 h-px bg-border" />
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
