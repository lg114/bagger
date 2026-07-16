import { useRef, useEffect, useState, useMemo, useCallback } from "react";
import { ChevronDown, Search, ChevronUp, ChevronDown as ArrowDown, X } from "lucide-react";
import MessageBubble from "./MessageBubble";
import type { Event } from "@/lib/api";

const BATCH_SIZE = 50;

interface ConversationViewProps {
  events: Event[];
  /** Controlled by the parent (SessionDetailPage) — opens the search bar. */
  searchOpen: boolean;
  /** Called when Ctrl+F is pressed (toggle search visibility). */
  onToggleSearch: () => void;
  /** Called to close the search bar (Esc, ✕, or session change). */
  onCloseSearch: () => void;
}

export default function ConversationView({ events, searchOpen, onToggleSearch, onCloseSearch }: ConversationViewProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [visibleCount, setVisibleCount] = useState(BATCH_SIZE);

  // ------ Search state ------
  const [searchQuery, setSearchQuery] = useState("");
  const [matchIndex, setMatchIndex] = useState(0);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const matchRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  // Compute matching event IDs (client-side, case-insensitive on content_text)
  const matchIds = useMemo(() => {
    if (!searchQuery.trim()) return [];
    const q = searchQuery.toLowerCase();
    return events
      .filter((e) => (e.content_text || "").toLowerCase().includes(q))
      .map((e) => e.event_id);
  }, [events, searchQuery]);

  // Reset match index when query changes
  useEffect(() => {
    setMatchIndex(0);
  }, [searchQuery]);

  // Clamp match index
  const safeMatchIndex = matchIds.length > 0 ? Math.min(matchIndex, matchIds.length - 1) : 0;
  const activeMatchId = matchIds.length > 0 ? matchIds[safeMatchIndex] : null;

  // ------ Keyboard: Ctrl+F / Esc ------
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault();
        onToggleSearch();
        setTimeout(() => searchInputRef.current?.focus(), 0);
      }
      if (e.key === "Escape" && searchOpen) {
        onCloseSearch();
        setSearchQuery("");
      }
      // Enter in search input → next match
      if (e.key === "Enter" && searchOpen && document.activeElement === searchInputRef.current) {
        e.preventDefault();
        if (e.shiftKey) {
          setMatchIndex((prev) => (prev > 0 ? prev - 1 : matchIds.length - 1));
        } else {
          setMatchIndex((prev) => (prev < matchIds.length - 1 ? prev + 1 : 0));
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [searchOpen, onToggleSearch, onCloseSearch, matchIds.length]);

  // ------ Scroll to active match ------
  useEffect(() => {
    if (activeMatchId) {
      const el = matchRefs.current.get(activeMatchId);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [activeMatchId]);

  // When events change (new session loaded), reset to first batch
  const firstEventId = events[0]?.event_id;
  useEffect(() => {
    setVisibleCount(BATCH_SIZE);
    onCloseSearch();
    setSearchQuery("");
  }, [firstEventId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll when loading more
  useEffect(() => {
    if (visibleCount > BATCH_SIZE && !activeMatchId) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [visibleCount, activeMatchId]);

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

  const navigateMatch = useCallback(
    (dir: 1 | -1) => () => {
      if (matchIds.length === 0) return;
      setMatchIndex((prev) => {
        const next = prev + dir;
        if (next < 0) return matchIds.length - 1;
        if (next >= matchIds.length) return 0;
        return next;
      });
    },
    [matchIds.length],
  );

  return (
    <div className="space-y-5 pb-6">
      {/* In-session search bar */}
      {searchOpen && (
        <div className="flex flex-wrap items-center gap-3 px-4 py-2.5 glass-card-static border-primary/20 animate-fade-in-up">
          <Search className="w-4 h-4 text-muted-foreground shrink-0" />
          <input
            ref={searchInputRef}
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search in conversation..."
            className="flex-1 min-w-[8rem] bg-transparent border-none outline-none text-sm text-foreground placeholder:text-muted-foreground font-mono"
            autoFocus
          />
          {matchIds.length > 0 && (
            <span className="text-xs text-muted-foreground font-mono tabular-nums shrink-0">
              {safeMatchIndex + 1} of {matchIds.length}
            </span>
          )}
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={navigateMatch(-1)}
              disabled={matchIds.length === 0}
              className="p-1 rounded hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors disabled:opacity-30 disabled:cursor-default"
              title="Previous match (Shift+Enter)"
            >
              <ChevronUp className="w-4 h-4" />
            </button>
            <button
              onClick={navigateMatch(1)}
              disabled={matchIds.length === 0}
              className="p-1 rounded hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors disabled:opacity-30 disabled:cursor-default"
              title="Next match (Enter)"
            >
              <ArrowDown className="w-4 h-4" />
            </button>
            <button
              onClick={() => { onCloseSearch(); setSearchQuery(""); }}
              className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
              title="Close search (Esc)"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Messages */}
      {visibleEvents.map((event, i) => {
        const isMatch = matchIds.includes(event.event_id);
        const isActive = event.event_id === activeMatchId;
        return (
          <div
            key={event.event_id}
            id={`msg-${event.event_id}`}
            ref={(el) => {
              if (el) matchRefs.current.set(event.event_id, el);
              else matchRefs.current.delete(event.event_id);
            }}
            className="animate-fade-in-up"
            style={{ animationDelay: `${i * 30}ms` }}
          >
            <MessageBubble
              event={event}
              highlight={isMatch}
              activeMatch={isActive}
            />
          </div>
        );
      })}

      {remaining > 0 && (
        <div className="flex flex-wrap items-center justify-center gap-3 py-4">
          <div className="flex-1 h-px bg-border min-w-[3rem]" />
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
          <div className="flex-1 h-px bg-border min-w-[3rem]" />
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
