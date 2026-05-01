import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import {
    Home,
    Activity,
    BookOpenCheck,
    Crosshair,
    BarChart3,
    Cog,
    LifeBuoy,
    FlaskConical,
    Shield,
    User,
} from "lucide-react";

import { apiGet } from "@/lib/api";
import { useSettings } from "@/lib/userMode";
import { useAuth } from "@/lib/AuthProvider";

// Cada item declara qué modos lo ven. "Avanzado" solo en experto.
const NAV_ITEMS = [
    { to: "/", label: "Inicio", icon: Home, code: "00", modes: ["novato", "experto"], adminOnly: false },
    { to: "/vivo", label: "En Vivo", icon: Activity, code: "01", modes: ["novato", "experto"], adminOnly: false },
    { to: "/operaciones", label: "Operaciones", icon: BookOpenCheck, code: "02", modes: ["novato", "experto"], adminOnly: false },
    { to: "/estrategias", label: "Estrategias", icon: Crosshair, code: "03", modes: ["novato", "experto"], adminOnly: false },
    { to: "/estadisticas", label: "Estadísticas", icon: BarChart3, code: "04", modes: ["novato", "experto"], adminOnly: false },
    { to: "/mi-cuenta", label: "Mi Cuenta", icon: User, code: "05", modes: ["novato", "experto"], adminOnly: false, userOnly: true },
    { to: "/configuracion", label: "Configuración", icon: Cog, code: "06", modes: ["novato", "experto"], adminOnly: true },
    { to: "/ayuda", label: "Ayuda", icon: LifeBuoy, code: "07", modes: ["novato", "experto"], adminOnly: false },
    { to: "/avanzado", label: "Avanzado", icon: FlaskConical, code: "08", modes: ["experto"], adminOnly: true },
    { to: "/admin", label: "Admin Panel", icon: Shield, code: "★", modes: ["novato", "experto"], adminOnly: true, adminAccent: true },
];

export default function Sidebar({ mobile = false, onNavigate }) {
    const { settings } = useSettings();
    const { isAdmin, isAuthenticated } = useAuth();
    const mode = settings?.mode || "novato";
    const visible = NAV_ITEMS.filter((it) => {
        if (!it.modes.includes(mode)) return false;
        if (it.adminOnly && !isAdmin) return false;
        // userOnly: solo se muestra si está logueado (no para anónimos)
        if (it.userOnly && !isAuthenticated) return false;
        return true;
    });

    // Bot status check para el header (igual que antes pero usa apiGet)
    const [botAlive, setBotAlive] = useState(null);
    useEffect(() => {
        const tick = async () => {
            try {
                const r = await apiGet("/process/list", { timeout: 3000 });
                const at = (r.data?.processes || []).find(
                    (p) => p.name === "auto_trader"
                );
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
    const stateColor = botAlive == null
        ? "bg-[var(--text-faint)]"
        : botAlive
        ? "bg-[var(--green)] pulse-dot"
        : "bg-[var(--red)]";
    const stateText = botAlive == null
        ? "text-[var(--text-faint)]"
        : botAlive
        ? "text-[var(--green)]"
        : "text-[var(--red)]";

    // Reglas de riesgo dinámicas leídas del preset activo
    const preset = settings?.active_style_preset || {};
    const riskPct = preset.risk_pct ?? "—";
    const dailyDD = preset.max_daily_loss_pct ?? "—";
    const maxPos = preset.max_open_positions ?? preset.max_pos ?? "—";

    const containerClasses = mobile
        ? "panel border-l-0 border-t-0 border-b-0 flex flex-col h-full"
        : "sidebar-nav lg-only fixed left-0 top-0 bottom-0 w-[var(--sidebar-w,240px)] panel border-r border-l-0 border-t-0 border-b-0 z-30 flex flex-col";

    return (
        <aside className={containerClasses} data-testid="sidebar">
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

            <nav className="flex-1 py-3 overflow-y-auto" data-testid="sidebar-nav">
                {visible.map((item) => {
                    const Icon = item.icon;
                    return (
                        <NavLink
                            key={item.to}
                            to={item.to}
                            end={item.to === "/"}
                            data-testid={`nav-${item.to.replace(/\//g, "-")}`}
                            onClick={onNavigate}
                            className={({ isActive }) =>
                                `relative flex items-center gap-3 px-5 py-2.5 text-sm transition-colors ${
                                    isActive
                                        ? "nav-active text-white bg-[var(--surface-2)]"
                                        : "text-[var(--text-dim)] hover:text-white hover:bg-[var(--surface-2)]"
                                }`
                            }
                        >
                            <span className="kicker w-5 text-[var(--text-faint)]">
                                {item.code}
                            </span>
                            <Icon size={15} strokeWidth={1.5} />
                            <span className="font-display font-semibold">
                                {item.label}
                            </span>
                        </NavLink>
                    );
                })}
            </nav>

            <div className="px-5 py-4 border-t border-[var(--border)]">
                <div className="kicker mb-1">REGLAS DE RIESGO</div>
                <div className="font-mono text-[11px] text-[var(--text-dim)]">
                    {riskPct}% / trade · {dailyDD}% diario · {maxPos} posición(es)
                </div>
                <div className="kicker mt-3 text-[var(--text-faint)] normal-case tracking-normal">
                    estilo: <span className="text-[var(--text-dim)]">{settings?.style || "balanceado"}</span>
                </div>
            </div>
        </aside>
    );
}
