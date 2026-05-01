// StylePresetCard — card seleccionable para el estilo de trading.
// Recibe el preset desde /api/settings/styles. Muestra emoji + label +
// descripción + 3 stats (risk, RR, max_pos). Border verde si active,
// badge "⭐ Recomendado" si recommended.

import { Star, Shield, Scale, Flame } from "lucide-react";

const STYLE_META = {
    conservativo: {
        Icon: Shield,
        emoji: "🛡️",
        title: "Conservativo",
        tagline: "Para quien recién empieza. Pierde poco si se equivoca.",
        accent: "var(--blue)",
    },
    balanceado: {
        Icon: Scale,
        emoji: "⚖️",
        title: "Balanceado",
        tagline: "Equilibrio entre riesgo y oportunidad. Recomendado.",
        accent: "var(--green-bright)",
    },
    agresivo: {
        Icon: Flame,
        emoji: "🔥",
        title: "Agresivo",
        tagline: "Más ganancia, pero también más caídas. Solo si entendés el riesgo.",
        accent: "var(--red)",
    },
};

export default function StylePresetCard({
    presetKey,
    preset = {},
    active = false,
    recommended = false,
    onClick,
    disabled = false,
}) {
    const meta = STYLE_META[presetKey] || {};
    const Icon = meta.Icon;
    const accent = meta.accent || "var(--text-dim)";

    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            data-testid={`style-preset-${presetKey}`}
            data-active={active ? "true" : "false"}
            className={`relative text-left p-5 border transition-all w-full ${
                active
                    ? "border-2 border-[var(--green)] bg-[var(--success-soft)]"
                    : "border border-[var(--border)] bg-[var(--surface)] hover:border-[var(--border-strong)]"
            } ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
            style={{ borderRadius: 4 }}
        >
            {recommended ? (
                <div
                    className="absolute -top-2 right-3 flex items-center gap-1 px-2 py-0.5 text-[10px] font-mono font-bold"
                    style={{
                        background: "var(--green-bright)",
                        color: "#000",
                    }}
                >
                    <Star size={10} fill="currentColor" />
                    RECOMENDADO
                </div>
            ) : null}

            <div className="flex items-start gap-3 mb-2">
                <div className="text-3xl leading-none">{meta.emoji}</div>
                <div className="flex-1">
                    <div className="font-display text-lg font-bold flex items-center gap-2">
                        {Icon ? <Icon size={16} style={{ color: accent }} /> : null}
                        {meta.title || presetKey}
                    </div>
                </div>
            </div>

            <p className="text-xs text-[var(--text-dim)] mb-4 leading-relaxed">
                {preset.description || meta.tagline}
            </p>

            <div className="grid grid-cols-3 gap-2 text-[10px] font-mono">
                <Stat
                    label="riesgo"
                    value={
                        preset.risk_pct != null
                            ? `${preset.risk_pct}%`
                            : "—"
                    }
                />
                <Stat
                    label="R:R mín"
                    value={
                        preset.min_rr != null
                            ? `1 : ${preset.min_rr}`
                            : "—"
                    }
                />
                <Stat
                    label="max pos"
                    value={preset.max_pos != null ? preset.max_pos : "—"}
                />
            </div>
        </button>
    );
}

function Stat({ label, value }) {
    return (
        <div className="border border-[var(--border)] px-2 py-1.5">
            <div className="kicker mb-0.5">{label}</div>
            <div className="font-mono tabular text-white">{value}</div>
        </div>
    );
}
