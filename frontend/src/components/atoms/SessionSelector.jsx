// SessionSelector — multi-toggle de sesiones de mercado.
// Reglas:
//   · Si "24/7" check → desmarca todas las otras (asia/london/ny).
//   · Si marca otra → desmarca "24/7".
//   · Si todas las otras quedan vacías y "24/7" no está marcado, fuerza "24/7".

import { Globe, Sun, Moon, Sunrise } from "lucide-react";

const SESSION_META = {
    "24/7": {
        Icon: Globe,
        title: "24/7",
        sub: "El bot opera siempre que el mercado esté abierto",
    },
    asia: {
        Icon: Moon,
        title: "Asia",
        sub: "00:00 – 09:00 UTC",
    },
    london: {
        Icon: Sunrise,
        title: "Londres",
        sub: "08:00 – 17:00 UTC",
    },
    ny: {
        Icon: Sun,
        title: "Nueva York",
        sub: "13:00 – 22:00 UTC",
    },
};

const ORDER = ["24/7", "asia", "london", "ny"];

export default function SessionSelector({
    value = ["24/7"],
    onChange,
    disabled = false,
}) {
    const isOn = (key) => (value || []).includes(key);

    const toggle = (key) => {
        if (disabled || !onChange) return;
        let next;
        if (key === "24/7") {
            // Si activamos 24/7 → solo 24/7
            next = isOn("24/7") ? [] : ["24/7"];
        } else {
            const without247 = (value || []).filter((s) => s !== "24/7");
            if (isOn(key)) {
                next = without247.filter((s) => s !== key);
            } else {
                next = [...without247, key];
            }
        }
        // Si todo quedó vacío, default 24/7
        if (next.length === 0) next = ["24/7"];
        onChange(next);
    };

    return (
        <div
            className="grid grid-cols-1 md:grid-cols-2 gap-2"
            data-testid="session-selector"
        >
            {ORDER.map((key) => {
                const meta = SESSION_META[key];
                const Icon = meta.Icon;
                const on = isOn(key);
                return (
                    <button
                        key={key}
                        type="button"
                        onClick={() => toggle(key)}
                        disabled={disabled}
                        data-testid={`session-${key.replace("/", "-")}`}
                        data-on={on ? "true" : "false"}
                        className={`flex items-start gap-3 p-3 text-left border transition-colors ${
                            on
                                ? "border-[var(--green)] bg-[var(--success-soft)]"
                                : "border-[var(--border)] hover:border-[var(--border-strong)]"
                        } ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                    >
                        <div
                            className={`mt-0.5 w-4 h-4 border flex items-center justify-center flex-shrink-0 ${
                                on
                                    ? "bg-[var(--green)] border-[var(--green)]"
                                    : "border-[var(--border-strong)]"
                            }`}
                        >
                            {on ? <span className="text-black text-[10px] leading-none">✓</span> : null}
                        </div>
                        <Icon size={14} className="mt-0.5 text-[var(--text-dim)]" />
                        <div className="flex-1 min-w-0">
                            <div className="font-mono text-sm font-semibold">
                                {meta.title}
                            </div>
                            <div className="text-[10px] text-[var(--text-faint)]">
                                {meta.sub}
                            </div>
                        </div>
                    </button>
                );
            })}
        </div>
    );
}
