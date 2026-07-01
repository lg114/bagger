import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  Home,
  MessageSquare,
  Search,
  BarChart3,
  RefreshCw,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import AppBar from "./AppBar";
import StatusBar from "./StatusBar";

const navItems = [
  { to: "/", icon: Home, label: "Dashboard" },
  { to: "/sessions", icon: MessageSquare, label: "Conversations" },
  { to: "/search", icon: Search, label: "Search" },
  { to: "/stats", icon: BarChart3, label: "Analytics" },
];

const bottomItems = [
  { to: "/import", icon: RefreshCw, label: "Scan" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="flex flex-col h-screen">
      {/* App Bar */}
      <AppBar
        onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
        sidebarOpen={sidebarOpen}
      />

      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <aside
          className={cn(
            "shrink-0 flex flex-col border-r border-border bg-surface transition-all duration-200 ease-apple",
            sidebarOpen ? "w-[220px]" : "w-0 overflow-hidden border-r-0",
          )}
        >
          <div className="flex flex-col h-full">
            {/* Main nav */}
            <nav className="flex-1 p-3 space-y-1">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2.5 px-3 py-2 rounded-element text-sm transition-all duration-200 ease-out",
                      isActive
                        ? "bg-primary/10 text-primary font-medium"
                        : "text-muted-foreground hover:text-foreground hover:bg-muted hover:translate-x-0.5",
                    )
                  }
                >
                  <item.icon className="w-[18px] h-[18px]" />
                  {item.label}
                </NavLink>
              ))}
            </nav>

            {/* Separator */}
            <div className="h-px bg-border mx-3" />

            {/* Bottom nav */}
            <nav className="p-3 space-y-1">
              {bottomItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2.5 px-3 py-2 rounded-element text-sm transition-all duration-200 ease-out",
                      isActive
                        ? "bg-primary/10 text-primary font-medium"
                        : "text-muted-foreground hover:text-foreground hover:bg-muted hover:translate-x-0.5",
                    )
                  }
                >
                  <item.icon className="w-[18px] h-[18px]" />
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
        </aside>

        {/* Main Content */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0">
          <main className="flex-1 overflow-y-auto">
            <div className="px-12 py-10 min-h-full">
              <Outlet />
            </div>
          </main>
        </div>
      </div>

      {/* Status Bar */}
      <StatusBar />
    </div>
  );
}
