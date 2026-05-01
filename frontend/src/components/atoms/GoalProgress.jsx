// GoalProgress — barra horizontal de progreso a la meta de capital.
// Calcula `% = (current - starting) / (goal - starting) * 100`.
// Color: verde si on-track, amber si lento, rojo si negativo.

import { Target } from "lucide-react";

const fmtMoney = (v) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return `$${n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
};

export default function GoalProgress({
    goal,
    current,
    starting,
    compact = false,
}) {
    const goalNum = Number(goal);
    const currentNum = Number(current);
    const startingNum = Number(starting);

    if (!goalNum || goalNum <= 0) {
        return (
            <div className={compact ? "" : "panel p-5"} data-testid="goal-progress-empty">
                <div className="kicker mb-1 flex items-center gap-2">
                    <Target size={12} className="text-[var(--novato-accent)]" />
                    META
                </div>
                <div className="text-sm text-[var(--text-dim)]">
                    Definí tu meta en{" "}
                    <a href="/configuracion" className="text-[var(--green-bright)] underline">
                        Configuración
                    </a>
                </div>
            </div>
        );
    }

    const distance = goalNum - startingNum;
    const progress = currentNum - startingNum;
    const pct = distance > 0 ? (progress / distance) * 100 : 0;
    const clampedPct = Math.max(0, Math.min(100, pct));
    const remaining = Math.max(0, goalNum - currentNum);

    let color, label;
    if (pct < 0) {
        color = "var(--red)";
        label = "Por debajo del inicio";
    } else if (pct < 25) {
        color = "var(--amber)";
        label = "Arrancando";
    } else if (pct < 75) {
        color = "var(--green)";
        label = "En camino";
    } else if (pct < 100) {
        color = "var(--green-bright)";
        label = "Cerca de la meta";
    } else {
        color = "var(--green-bright)";
        label = "🎉 Meta alcanzada";
    }

    const inner = (
        <>
            <div className="flex items-center justify-between mb-2">
                <div className="kicker flex items-center gap-2">
                    <Target size={12} className="text-[var(--novato-accent)]" />
                    PROGRESO A LA META
                </div>
                <div className="text-[10px] font-mono text-[var(--text-faint)]">
                    {label}
                </div>
            </div>
            <div className="flex items-baseline gap-2 flex-wrap mb-3">
                <div className="font-display text-xl font-bold tabular">
                    {fmtMoney(currentNum)}
                </div>
                <div className="text-[var(--text-dim)] font-mono text-xs">
                    de {fmtMoney(goalNum)}
                </div>
                <div
                    className="ml-auto font-mono text-sm tabular font-semibold"
                    style={{ color }}
                >
                    {clampedPct.toFixed(1)}%
                </div>
            </div>
            <div
                className="relative h-2 bg-[var(--bg)] border border-[var(--border)]"
                role="progressbar"
                aria-valuenow={clampedPct}
                aria-valuemin={0}
                aria-valuemax={100}
            >
                <div
                    className="absolute top-0 left-0 bottom-0 transition-all"
                    style={{
                        width: `${clampedPct}%`,
                        background: color,
                    }}
                />
            </div>
            {remaining > 0 ? (
                <div className="kicker mt-2 normal-case tracking-normal text-[var(--text-dim)]">
                    Te falta {fmtMoney(remaining)} para llegar a la meta.
                </div>
            ) : (
                <div className="kicker mt-2 normal-case tracking-normal text-[var(--green-bright)]">
                    Llegaste. Considerá ajustar tu meta hacia arriba.
                </div>
            )}
        </>
    );

    if (compact) return <div data-testid="goal-progress">{inner}</div>;
    return (
        <div className="panel p-5" data-testid="goal-progress">
            {inner}
        </div>
    );
}
