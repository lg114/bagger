import { useState, useCallback } from "react";
import { Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";

interface SearchBarProps {
  initialQuery?: string;
  onSearch: (query: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}

export default function SearchBar({
  initialQuery = "",
  onSearch,
  placeholder = "Search conversations...",
  autoFocus = false,
}: SearchBarProps) {
  const [value, setValue] = useState(initialQuery);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = value.trim();
      if (trimmed) {
        onSearch(trimmed);
      }
    },
    [value, onSearch],
  );

  const handleClear = useCallback(() => {
    setValue("");
  }, []);

  return (
    <form onSubmit={handleSubmit} className="relative search-glow">
      <Search className="absolute left-5 top-1/2 -translate-y-1/2 w-5 h-5 text-primary/40" />
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder}
        autoFocus={autoFocus}
        className="w-full pl-14 pr-24 py-4 glass-card-static text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/35 text-lg transition-all duration-300 ease-apple"
      />
      <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-2">
        {value && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-muted-foreground hover:text-primary"
            onClick={handleClear}
          >
            <X className="w-4 h-4" />
          </Button>
        )}
        <Button
          type="submit"
          size="sm"
          disabled={!value.trim()}
          className="border border-primary/15 bg-transparent text-primary hover:bg-primary hover:text-primary-foreground transition-all duration-300 ease-apple"
        >
          Search
        </Button>
      </div>
    </form>
  );
}
