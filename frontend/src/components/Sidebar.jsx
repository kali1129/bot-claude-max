import { useEffect, useState } from "react";
import axios from "axios";
import {
    Activity,
    LayoutDashboard,
    Sliders,
    Cog,
    BookOpenCheck,
} from "lucide-react";

const NAV_ITEMS = [
    { id: "live",     label: "En Vivo",              icon: Activity,         code: "00" },
    { id: "overview", label: "Plan",                 icon: LayoutDashboard,  code: "01" },
    { id: "control",  label: "Panel de Control",     icon: Sliders,          code: "02" },
    { id: "config",   label: "Configuración",        icon: Cog,              code: "03" },
    { id: "journal",  label: "Diario de Operaciones", icon: BookOpenCheck,   code: "04" },
];

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function Sidebar({ activeSection }) {
    // Pull live bot status so the header isn't lying about "ACTIVO" when
    // auto_trader is dead. Refresh every 5 s — cheap call.
    const [botAlive, setBotAlive] = useState(null);
    useEffect(() => {
        const tick = async () => {
            try {
                const r = await axios.get(`${API}/process/list`, { timeout: 3000 });
                const at = (r.data?.processes || []).find((p) => p.name === "auto_trader");
                setBotAlive(!!at?.alive);
            } catch {
                setBotAlive(false);
            }
        };
        tick();
        const id = setInterval(tick, 5000);
        return () => clearInterval(id);
    }, []);

    const stateLabel = botAlive == null ? "// CARGANDO" : botAlive ? "// BOT ACTIVO" : "// BOT PARADO";
    const stateColor = botAlive == null ? "bg-[var(--text-faint)]"
                       : botAlive ? "bg-[var(--green)] pulse-dot"
                       : "bg-[var(--red)]";
    const stateText  = botAlive == null ? "text-[var(--text-faint)]"
                       : botAlive ? "text-[var(--green)]"
                       : "text-[var(--red)]";

    return (
        <aside
            className="sidebar-nav fixed left-0 top-0 bottom-0 w-[240px] panel border-r border-l-0 border-t-0 border-b-0 z-30 flex flex-col"
            data-testid="sidebar"
        >
            <div className="px-5 py-5 border-b border-[var(--border)]">
                <div className="flex items-center gap-2">
                    <div
                        className={`w-2 h-2 ${stateColor}`}
                        data-testid="live-indicator"
                    />
                    <span className={`kicker ${stateText}`}>{stateLabel}</span>
                </div>
                <div className="font-display text-2xl font-black mt-2 tracking-tight">
                    OPS<span className="text-[var(--green)]">.</span>
                </div>
                <div className="kicker mt-1">TRADING AUTOMÁTICO</div>
            </div>

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

            <div className="px-5 py-4 border-t border-[var(--border)]">
                <div className="kicker mb-1">REGLAS DE RIESGO</div>
                <div className="font-mono text-[11px] text-[var(--text-dim)]">
                    1% / trade · 3% diario · 1 posición
                </div>
            </div>
        </aside>
    );
}
