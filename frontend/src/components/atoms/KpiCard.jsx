// KpiCard — reemplazo unificado de MetricBig (Overview), MetricCard (ProMetrics)
// y los div panels de TradeJournal stats. Antes había 3 implementaciones del
// mismo patrón.

const COLOR_CLASS = {
    white: "text-white",
    green: "text-[var(--green-bright)]",
    red: "text-[var(--red)]",
    amber: "text-[var(--amber)]",
    blue: "text-[var(--blue)]",
    novato: "text-[var(--novato-accent)]",
};

export default function KpiCard({
    label,
    value,
    sublabel,
    color = "white",
    icon: Icon = null,
    soft = false,
    big = false,
    testId,
}) {
    const colorClass = COLOR_CLASS[color] || COLOR_CLASS.white;
    const valueSize = big ? "text-4xl" : "text-2xl md:text-3xl";

    return (
        <div className={soft ? "panel-soft" : "panel p-5"} data-testid={testId}>
            <div className="kicker mb-3 flex items-center gap-2">
                {Icon ? <Icon size={12} className="text-[var(--text-faint)]" /> : null}
                {label}
            </div>
            <div
                className={`font-mono ${valueSize} font-bold tabular ${colorClass}`}
            >
                {value}
            </div>
            {sublabel ? (
                <div className="kicker mt-2 normal-case tracking-normal text-[var(--text-dim)]">
                    {sublabel}
                </div>
            ) : null}
        </div>
    );
}
