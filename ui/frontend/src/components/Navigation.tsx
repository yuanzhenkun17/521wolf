import { NavLink } from "react-router-dom";
import { Gamepad2, GitBranch } from "lucide-react";

const NAV_ITEMS = [
  { to: "/", label: "普通对战", icon: Gamepad2 },
  { to: "/roles", label: "自进化", icon: GitBranch },
];

export function Navigation() {
  return (
    <nav className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center gap-1 px-5 py-2">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              isActive
                ? "flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
                : "flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
            }
          >
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
