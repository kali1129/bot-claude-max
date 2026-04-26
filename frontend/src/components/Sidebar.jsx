import {
    LayoutDashboard,
    Server,
    Crosshair,
    ShieldAlert,
    CheckSquare,
    Calculator,
    BookOpenCheck,
    Wrench,
    Brain,
} from "lucide-react";

const NAV_ITEMS = [
    { id: "overview", label: "Overview", icon: LayoutDashboard, code: "00" },
    { id: "mcps", label: "MCP Stack", icon: Server, code: "01" },
    { id: "strategies", label: "Strategies", icon: Crosshair, code: "02" },
    { id: "rules", label: "Strict Rules", icon: ShieldAlert, code: "03" },
    { id: "checklist", label: "Daily Checklist", icon: CheckSquare, code: "04" },
    { id: "risk-calc", label: "Risk Calc", icon: Calculator, code: "05" },
    { id: "journal", label: "Trade Journal", icon: BookOpenCheck, code: "06" },
    { id: "setup", label: "Setup Guide", icon: Wrench, code: "07" },
    { id: "mindset", label: "Mindset", icon: Brain, code: "08" },
];

export default function Sidebar({ activeSection }) {
    return (
        <aside
            className="sidebar-nav fixed left-0 top-0 bottom-0 w-[240px] panel border-r border-l-0 border-t-0 border-b-0 z-30 flex flex-col"
            data-testid="sidebar"
        >
            {/* Logo block */}
            <div className="px-5 py-5 border-b border-[var(--border)]">
                <div className="flex items-center gap-2">
                    <div
                        className="w-2 h-2 bg-[var(--green)] pulse-dot"
                        data-testid="live-indicator"
                    />
                    <span className="kicker text-[var(--green)]">// LIVE</span>
                </div>
                <div className="font-display text-2xl font-black mt-2 tracking-tight">
                    OPS<span className="text-[var(--green)]">.</span>
                </div>
                <div className="kicker mt-1">$800 FUTURES PLAN</div>
            </div>

            {/* Nav */}
            <nav className="flex-1 py-3" data-testid="sidebar-nav">
                {NAV_ITEMS.map((item) => {
                    const Icon = item.icon;
                    const active = activeSection === item.id;
                    return (
                        <a
                            key={item.id}
                            href={`#${item.id}`}
                            data-testid={`nav-${item.id}`}
                            className={`relative flex items-center gap-3 px-5 py-2.5 text-sm transition-colors ${
                                active
                                    ? "nav-active text-white bg-[var(--surface-2)]"
                                    : "text-[var(--text-dim)] hover:text-white hover:bg-[var(--surface-2)]"
                            }`}
                        >
                            <span className="kicker w-5 text-[var(--text-faint)]">
                                {item.code}
                            </span>
                            <Icon size={15} strokeWidth={1.5} />
                            <span className="font-display font-semibold">
                                {item.label}
                            </span>
                        </a>
                    );
                })}
            </nav>

            {/* Footer */}
            <div className="px-5 py-4 border-t border-[var(--border)]">
                <div className="kicker mb-1">RISK MODEL</div>
                <div className="font-mono text-[11px] text-[var(--text-dim)]">
                    1% / trade · 3% daily · 1pos
                </div>
            </div>
        </aside>
    );
}
