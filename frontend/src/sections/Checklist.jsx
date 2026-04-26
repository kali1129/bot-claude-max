import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { Check, Sun, Activity, Moon } from "lucide-react";
import { toast } from "sonner";

const SECTION_META = [
    { key: "pre_market", label: "Pre-mercado", icon: Sun, code: "04A" },
    { key: "during_market", label: "Durante mercado", icon: Activity, code: "04B" },
    { key: "post_market", label: "Post-mercado", icon: Moon, code: "04C" },
];

export default function Checklist({ checklist, api }) {
    const today = new Date().toISOString().slice(0, 10);
    const [checked, setChecked] = useState(new Set());
    const [loading, setLoading] = useState(true);

    const load = useCallback(async () => {
        try {
            const res = await axios.get(`${api}/checklist/${today}`);
            setChecked(new Set(res.data.checked_ids || []));
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }, [api, today]);

    useEffect(() => {
        load();
    }, [load]);

    const persist = async (newSet) => {
        try {
            await axios.post(`${api}/checklist`, {
                date: today,
                checked_ids: Array.from(newSet),
            });
        } catch (e) {
            toast.error("Error guardando checklist");
        }
    };

    const toggle = (id) => {
        const next = new Set(checked);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        setChecked(next);
        persist(next);
    };

    const total =
        checklist.pre_market.length +
        checklist.during_market.length +
        checklist.post_market.length;
    const done = checked.size;
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;

    return (
        <section
            id="checklist"
            className="px-6 py-12 border-b border-[var(--border)]"
            data-testid="section-checklist"
        >
            <div className="max-w-[1400px] mx-auto">
                <div className="mb-8 flex items-end justify-between flex-wrap gap-4">
                    <div>
                        <div className="kicker mb-2">
                            SECTION 04 / DAILY CHECKLIST · {today}
                        </div>
                        <h2 className="font-display text-3xl md:text-4xl font-black tracking-tight">
                            Ritual diario
                            <span className="text-[var(--green)]">.</span>
                        </h2>
                        <p className="mt-3 text-[var(--text-dim)] max-w-[640px] leading-relaxed">
                            18 puntos divididos en pre-mercado, durante mercado y
                            post-mercado. El estado se guarda y se reinicia cada
                            día UTC. Si no completas pre-mercado, no abres
                            posición.
                        </p>
                    </div>
                    <div
                        className="panel px-5 py-4 flex items-center gap-4"
                        data-testid="checklist-progress"
                    >
                        <div>
                            <div className="kicker mb-0.5">PROGRESO</div>
                            <div className="font-mono text-2xl font-semibold tabular">
                                {done}/{total}
                            </div>
                        </div>
                        <div className="w-32">
                            <div className="h-1.5 bg-[var(--border)] relative">
                                <div
                                    className="h-full bg-[var(--green)] transition-all duration-300"
                                    style={{ width: `${pct}%` }}
                                />
                            </div>
                            <div className="kicker text-[var(--green-bright)] mt-1.5">
                                {pct}% complete
                            </div>
                        </div>
                    </div>
                </div>

                {loading ? (
                    <div className="kicker">// LOADING…</div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                        {SECTION_META.map((meta) => {
                            const Icon = meta.icon;
                            const items = checklist[meta.key];
                            const sectionDone = items.filter((i) =>
                                checked.has(i.id)
                            ).length;
                            return (
                                <div
                                    key={meta.key}
                                    className="panel"
                                    data-testid={`checklist-${meta.key}`}
                                >
                                    <div className="px-4 py-3 border-b border-[var(--border)] flex items-center justify-between">
                                        <div className="flex items-center gap-2">
                                            <Icon
                                                size={14}
                                                className="text-[var(--green-bright)]"
                                            />
                                            <h3 className="font-display font-bold tracking-tight">
                                                {meta.label}
                                            </h3>
                                        </div>
                                        <span className="kicker">
                                            {sectionDone}/{items.length}
                                        </span>
                                    </div>
                                    <ul className="p-2">
                                        {items.map((it) => {
                                            const isChecked = checked.has(it.id);
                                            return (
                                                <li
                                                    key={it.id}
                                                    onClick={() => toggle(it.id)}
                                                    data-testid={`checkitem-${it.id}`}
                                                    className={`flex items-start gap-3 px-3 py-2.5 cursor-pointer transition-colors hover:bg-[var(--surface-2)] ${
                                                        isChecked
                                                            ? "opacity-50"
                                                            : ""
                                                    }`}
                                                >
                                                    <span
                                                        className={`check-box ${isChecked ? "checked" : ""}`}
                                                    >
                                                        {isChecked && (
                                                            <Check
                                                                size={12}
                                                                strokeWidth={3}
                                                            />
                                                        )}
                                                    </span>
                                                    <span
                                                        className={`text-[13px] leading-snug ${
                                                            isChecked
                                                                ? "line-through"
                                                                : ""
                                                        }`}
                                                    >
                                                        {it.text}
                                                    </span>
                                                </li>
                                            );
                                        })}
                                    </ul>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </section>
    );
}
