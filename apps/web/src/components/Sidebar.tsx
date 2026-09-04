import { NavLink } from "react-router-dom";
import {
  BarChart3,
  Users,
  Activity,
  LifeBuoy,
  ClipboardList,
  Briefcase,
  CalendarClock,
  Rocket,
  Network,
  Bell,
  Shield,
  Settings,
  FileSearch,
  BookOpen,
} from "lucide-react";

interface NavItem {
  to: string;
  label: string;
  Icon: typeof BarChart3;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", Icon: BarChart3 },
  { to: "/learners", label: "Learners", Icon: Users },
  { to: "/behavior", label: "Behavior", Icon: Activity },
  { to: "/supports", label: "Supports", Icon: LifeBuoy },
  { to: "/assessments", label: "Assessments", Icon: ClipboardList },
  { to: "/workforce", label: "Workforce", Icon: Briefcase },
  { to: "/activities", label: "Activities", Icon: CalendarClock },
  { to: "/readiness", label: "Readiness", Icon: Rocket },
  { to: "/correlations", label: "Correlations", Icon: Network },
  { to: "/alerts", label: "Alerts", Icon: Bell },
  { to: "/access", label: "Access", Icon: Shield },
  { to: "/settings", label: "Settings", Icon: Settings },
  { to: "/ai-audit", label: "AI Audit", Icon: FileSearch },
  { to: "/demo-guide", label: "Demo Guide", Icon: BookOpen },
];

export function Sidebar() {
  return (
    <aside
      aria-label="Primary navigation"
      className="hidden md:flex md:w-60 md:flex-col md:bg-slate-950 md:border-r md:border-slate-800"
    >
      <div className="px-5 py-5 border-b border-slate-800">
        <div className="text-sm uppercase tracking-widest text-slate-400">Prototype</div>
        <div className="text-lg font-semibold text-slate-100">Support Guide</div>
      </div>
      <nav aria-label="Sections" className="flex-1 overflow-y-auto py-3">
        <ul className="space-y-1 px-2">
          {NAV_ITEMS.map(({ to, label, Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  [
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm",
                    "text-slate-300 hover:bg-slate-800 hover:text-slate-100",
                    isActive ? "bg-slate-800 text-white ring-1 ring-sky-500/40" : "",
                  ].join(" ")
                }
              >
                <Icon aria-hidden="true" className="h-4 w-4" />
                <span>{label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div className="border-t border-slate-800 px-4 py-3 text-xs text-slate-500">
        Prototype v0.3.0 - synthetic data
      </div>
    </aside>
  );
}
