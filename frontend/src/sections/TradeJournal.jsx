import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { Trash2, Plus, ChevronDown, ChevronUp } from "lucide-react";
import { toast } from "sonner";
import {
    LineChart,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    ReferenceLine,
} from "recharts";
import ResearchLog from "./ResearchLog";

const COMMON_SYMBOLS = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "XAUUSD",
    "NAS100",
    "US30",
    "DAX",
    "BTCUSD",
    "ETHUSD",
];

function emptyForm(strategies, today) {
    return {
        date: today,
        symbol: "EURUSD",
        side: "buy",
        strategy: strategies?.[0]?.name || "",
        entry: "",
        exit: "",
        sl: "",
        tp: "",
        lots: "",
        pnl_usd: "",
        r_multiple: "",
        status: "closed-win",
        notes: "",
    };
}

export default function TradeJournal({ api, strategies, stats, onMutated }) {
    const today = new Date().toISOString().slice(0, 10);
    const [trades, setTrades] = useState([]);
    const [form, setForm] = useState(emptyForm(strategies, today));
    const [showForm, setShowForm] = useState(false);
    const [submitting, setSubmitting] = useState(false);

    const load = useCallback(async () => {
        try {
            const res = await axios.get(`${api}/journal`);
            setTrades(res.data);
        } catch (e) {
            console.error(e);
        }
    }, [api]);

    useEffect(() => {
        load();
    }, [load]);

    const handleField = (k, v) => setForm((f) => ({ ...f, [k]: v }));

    const submit = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        try {
            const payload = {
                ...form,
                entry: parseFloat(form.entry || 0),
                exit: form.exit ? parseFloat(form.exit) : null,
                sl: parseFloat(form.sl || 0),
                tp: form.tp ? parseFloat(form.tp) : null,
                lots: parseFloat(form.lots || 0),
                pnl_usd: parseFloat(form.pnl_usd || 0),
                r_multiple: parseFloat(form.r_multiple || 0),
            };
            await axios.post(`${api}/journal`, payload);
            toast.success("Trade registrado");
            setForm(emptyForm(strategies, today));
            setShowForm(false);
            await load();
            onMutated?.();
        } catch (e) {
            toast.error("Error guardando trade");
        } finally {
            setSubmitting(false);
        }
    };

    const remove = async (id) => {
        if (!window.confirm("¿Borrar este trade del diario?")) return;
        try {
            await axios.delete(`${api}/journal/${id}`);
            toast.success("Trade borrado");
            await load();
            onMutated?.();
        } catch (e) {
            toast.error("No se pudo borrar");
        }
    };

    const equity = stats?.equity_curve || [];
    // Baseline = starting equity from stats (the first equity sample) or 0
    // when there's no data. Earlier hardcoded $800 was the original plan
    // capital; the bot's actual capital is whatever MT5 reports. Keeping
    // this dynamic stops the journal lying about a $600 phantom drawdown
    // when the user starts with a different balance.
    const baseline = equity.length > 0 ? equity[0].equity : 0;
    const minE = equity.length ? Math.min(...equity.map((e) => e.equity)) : baseline;
    const maxE = equity.length ? Math.max(...equity.map((e) => e.equity)) : baseline;
    const yPad = Math.max(5, (maxE - minE) * 0.1);

    return (
        <section
            id="journal"
            className="px-6 py-12 border-b border-[var(--border)]"
            data-testid="section-journal"
        >
            <div className="max-w-[1400px] mx-auto">
                <div className="mb-8 flex items-end justify-between flex-wrap gap-4">
                    <div>
                        <div className="kicker mb-2">SECTION 06 / JOURNAL</div>
                        <h2 className="font-display text-3xl md:text-4xl font-black tracking-tight">
                            Trade journal
                            <span className="text-[var(--green)]">.</span>
                        </h2>
                        <p className="mt-3 text-[var(--text-dim)] max-w-[640px] leading-relaxed">
                            Cada trade se registra. Sin journal no hay edge.
                            Anota razón, screenshot y aprendizaje. La equity curve
                            se actualiza al cerrar.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={() => setShowForm((s) => !s)}
                        className="btn-sharp primary"
                        data-testid="add-trade-toggle"
                    >
                        {showForm ? (
                            <>
                                <ChevronUp size={12} className="inline mr-1" />
                                Cerrar
                            </>
                        ) : (
                            <>
                                <Plus size={12} className="inline mr-1" />
                                Registrar Trade
                            </>
                        )}
                    </button>
                </div>

                {/* Stats strip */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                    <div className="panel p-4" data-testid="journal-total-trades">
                        <div className="kicker mb-1">TOTAL TRADES</div>
                        <div className="font-mono text-2xl font-bold tabular">
                            {stats?.total_trades ?? 0}
                        </div>
                    </div>
                    <div className="panel p-4" data-testid="journal-winrate">
                        <div className="kicker mb-1">WIN RATE</div>
                        <div className="font-mono text-2xl font-bold tabular">
                            {stats?.win_rate?.toFixed(1) ?? 0}%
                        </div>
                    </div>
                    <div className="panel p-4" data-testid="journal-expectancy">
                        <div className="kicker mb-1">EXPECTANCY</div>
                        <div className="font-mono text-2xl font-bold tabular text-[var(--green-bright)]">
                            {stats?.expectancy >= 0 ? "+" : ""}
                            {stats?.expectancy?.toFixed(2) ?? "0.00"}R
                        </div>
                    </div>
                    <div className="panel p-4" data-testid="journal-total-pnl">
                        <div className="kicker mb-1">TOTAL P&L</div>
                        <div
                            className={`font-mono text-2xl font-bold tabular ${stats?.total_pnl_usd > 0 ? "text-[var(--green-bright)]" : stats?.total_pnl_usd < 0 ? "text-[var(--red)]" : ""}`}
                        >
                            {stats?.total_pnl_usd >= 0 ? "+" : ""}$
                            {stats?.total_pnl_usd?.toFixed(2) ?? "0.00"}
                        </div>
                    </div>
                </div>

                {/* Form */}
                {showForm && (
                    <form
                        onSubmit={submit}
                        className="panel p-5 mb-3"
                        data-testid="trade-form"
                    >
                        <div className="kicker mb-4">// NUEVO TRADE</div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            <div>
                                <div className="kicker mb-1">Date</div>
                                <input
                                    type="date"
                                    value={form.date}
                                    onChange={(e) =>
                                        handleField("date", e.target.value)
                                    }
                                    className="input-sharp"
                                    data-testid="form-date"
                                    required
                                />
                            </div>
                            <div>
                                <div className="kicker mb-1">Symbol</div>
                                <input
                                    list="symbols"
                                    value={form.symbol}
                                    onChange={(e) =>
                                        handleField("symbol", e.target.value)
                                    }
                                    className="input-sharp"
                                    data-testid="form-symbol"
                                    required
                                />
                                <datalist id="symbols">
                                    {COMMON_SYMBOLS.map((s) => (
                                        <option key={s} value={s} />
                                    ))}
                                </datalist>
                            </div>
                            <div>
                                <div className="kicker mb-1">Side</div>
                                <select
                                    value={form.side}
                                    onChange={(e) =>
                                        handleField("side", e.target.value)
                                    }
                                    className="input-sharp"
                                    data-testid="form-side"
                                >
                                    <option value="buy">BUY</option>
                                    <option value="sell">SELL</option>
                                </select>
                            </div>
                            <div>
                                <div className="kicker mb-1">Strategy</div>
                                <select
                                    value={form.strategy}
                                    onChange={(e) =>
                                        handleField("strategy", e.target.value)
                                    }
                                    className="input-sharp"
                                    data-testid="form-strategy"
                                >
                                    {strategies?.map((s) => (
                                        <option key={s.id} value={s.name}>
                                            {s.name}
                                        </option>
                                    ))}
                                </select>
                            </div>

                            <div>
                                <div className="kicker mb-1">Entry</div>
                                <input
                                    type="number"
                                    step="any"
                                    value={form.entry}
                                    onChange={(e) =>
                                        handleField("entry", e.target.value)
                                    }
                                    className="input-sharp"
                                    data-testid="form-entry"
                                    required
                                />
                            </div>
                            <div>
                                <div className="kicker mb-1">Exit</div>
                                <input
                                    type="number"
                                    step="any"
                                    value={form.exit}
                                    onChange={(e) =>
                                        handleField("exit", e.target.value)
                                    }
                                    className="input-sharp"
                                    data-testid="form-exit"
                                />
                            </div>
                            <div>
                                <div className="kicker mb-1">SL</div>
                                <input
                                    type="number"
                                    step="any"
                                    value={form.sl}
                                    onChange={(e) =>
                                        handleField("sl", e.target.value)
                                    }
                                    className="input-sharp"
                                    data-testid="form-sl"
                                    required
                                />
                            </div>
                            <div>
                                <div className="kicker mb-1">TP</div>
                                <input
                                    type="number"
                                    step="any"
                                    value={form.tp}
                                    onChange={(e) =>
                                        handleField("tp", e.target.value)
                                    }
                                    className="input-sharp"
                                    data-testid="form-tp"
                                />
                            </div>

                            <div>
                                <div className="kicker mb-1">Lots</div>
                                <input
                                    type="number"
                                    step="any"
                                    value={form.lots}
                                    onChange={(e) =>
                                        handleField("lots", e.target.value)
                                    }
                                    className="input-sharp"
                                    data-testid="form-lots"
                                    required
                                />
                            </div>
                            <div>
                                <div className="kicker mb-1">P&L USD</div>
                                <input
                                    type="number"
                                    step="any"
                                    value={form.pnl_usd}
                                    onChange={(e) =>
                                        handleField("pnl_usd", e.target.value)
                                    }
                                    className="input-sharp"
                                    data-testid="form-pnl"
                                />
                            </div>
                            <div>
                                <div className="kicker mb-1">R multiple</div>
                                <input
                                    type="number"
                                    step="any"
                                    value={form.r_multiple}
                                    onChange={(e) =>
                                        handleField("r_multiple", e.target.value)
                                    }
                                    className="input-sharp"
                                    data-testid="form-r"
                                    placeholder="ej: 1.8"
                                />
                            </div>
                            <div>
                                <div className="kicker mb-1">Status</div>
                                <select
                                    value={form.status}
                                    onChange={(e) =>
                                        handleField("status", e.target.value)
                                    }
                                    className="input-sharp"
                                    data-testid="form-status"
                                >
                                    <option value="open">OPEN</option>
                                    <option value="closed-win">WIN</option>
                                    <option value="closed-loss">LOSS</option>
                                    <option value="closed-be">BREAK-EVEN</option>
                                </select>
                            </div>

                            <div className="col-span-2 md:col-span-4">
                                <div className="kicker mb-1">Notes (qué aprendí, screenshot link, razón)</div>
                                <textarea
                                    value={form.notes}
                                    onChange={(e) =>
                                        handleField("notes", e.target.value)
                                    }
                                    rows="2"
                                    className="input-sharp"
                                    data-testid="form-notes"
                                />
                            </div>
                        </div>

                        <div className="mt-4 flex justify-end gap-2">
                            <button
                                type="button"
                                onClick={() => setShowForm(false)}
                                className="btn-sharp"
                                data-testid="form-cancel"
                            >
                                Cancelar
                            </button>
                            <button
                                type="submit"
                                disabled={submitting}
                                className="btn-sharp primary"
                                data-testid="form-submit"
                            >
                                {submitting ? "GUARDANDO…" : "GUARDAR TRADE"}
                            </button>
                        </div>
                    </form>
                )}

                {/* Research log — per-trade post-mortem feedback */}
                <ResearchLog api={api} />

                {/* Equity curve */}
                <div className="panel p-5 mb-3" data-testid="equity-curve">
                    <div className="flex items-center justify-between mb-4">
                        <div className="kicker">// EQUITY CURVE</div>
                        <div className="font-mono text-[11px] text-[var(--text-dim)]">
                            base: ${baseline.toFixed(2)}
                        </div>
                    </div>
                    {equity.length === 0 ? (
                        <div className="h-[220px] flex items-center justify-center text-[var(--text-faint)] font-mono text-[12px]">
                            Sin trades cerrados aún. Registra tu primer trade.
                        </div>
                    ) : (
                        <div className="h-[260px]">
                            <ResponsiveContainer width="100%" height="100%">
                                <LineChart
                                    data={equity.map((e, i) => ({
                                        ...e,
                                        idx: i + 1,
                                    }))}
                                >
                                    <CartesianGrid
                                        strokeDasharray="2 4"
                                        stroke="#27272a"
                                    />
                                    <XAxis
                                        dataKey="idx"
                                        stroke="#71717a"
                                        tick={{
                                            fontSize: 10,
                                            fontFamily: "JetBrains Mono",
                                        }}
                                    />
                                    <YAxis
                                        domain={[minE - yPad, maxE + yPad]}
                                        stroke="#71717a"
                                        tick={{
                                            fontSize: 10,
                                            fontFamily: "JetBrains Mono",
                                        }}
                                    />
                                    <Tooltip
                                        contentStyle={{
                                            background: "#121214",
                                            border: "1px solid #27272a",
                                            borderRadius: 0,
                                            fontFamily: "JetBrains Mono",
                                            fontSize: 11,
                                        }}
                                    />
                                    <ReferenceLine
                                        y={baseline}
                                        stroke="#71717a"
                                        strokeDasharray="3 3"
                                    />
                                    <Line
                                        type="stepAfter"
                                        dataKey="equity"
                                        stroke="#10b981"
                                        strokeWidth={1.5}
                                        dot={{ r: 2, fill: "#10b981" }}
                                    />
                                </LineChart>
                            </ResponsiveContainer>
                        </div>
                    )}
                </div>

                {/* Table */}
                <div
                    className="panel overflow-x-auto"
                    data-testid="trades-table-wrap"
                >
                    <table className="w-full text-left">
                        <thead>
                            <tr className="border-b border-[var(--border)]">
                                {[
                                    "DATE",
                                    "SYMBOL",
                                    "SIDE",
                                    "STRATEGY",
                                    "ENTRY",
                                    "EXIT",
                                    "LOTS",
                                    "P&L",
                                    "R",
                                    "STATUS",
                                    "",
                                ].map((h) => (
                                    <th
                                        key={h}
                                        className="kicker px-3 py-2.5 text-left whitespace-nowrap"
                                    >
                                        {h}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {trades.length === 0 ? (
                                <tr>
                                    <td
                                        colSpan="11"
                                        className="px-3 py-8 text-center text-[var(--text-faint)] font-mono text-[12px]"
                                        data-testid="no-trades"
                                    >
                                        // sin trades aún
                                    </td>
                                </tr>
                            ) : (
                                trades.map((t) => (
                                    <tr
                                        key={t.id}
                                        className="border-b border-[var(--border)] hover:bg-[var(--surface-2)] transition-colors"
                                        data-testid={`trade-row-${t.id}`}
                                    >
                                        <td className="px-3 py-2 font-mono text-[12px] text-[var(--text-dim)]">
                                            {t.date}
                                        </td>
                                        <td className="px-3 py-2 font-mono text-[12px] font-semibold">
                                            {t.symbol}
                                        </td>
                                        <td
                                            className={`px-3 py-2 font-mono text-[11px] uppercase ${t.side === "buy" ? "text-[var(--green-bright)]" : "text-[var(--red)]"}`}
                                        >
                                            {t.side}
                                        </td>
                                        <td className="px-3 py-2 text-[12px] text-[var(--text-dim)] max-w-[200px] truncate">
                                            {t.strategy}
                                        </td>
                                        <td className="px-3 py-2 font-mono text-[12px] tabular">
                                            {t.entry}
                                        </td>
                                        <td className="px-3 py-2 font-mono text-[12px] tabular text-[var(--text-dim)]">
                                            {t.exit ?? "—"}
                                        </td>
                                        <td className="px-3 py-2 font-mono text-[12px] tabular">
                                            {t.lots}
                                        </td>
                                        <td
                                            className={`px-3 py-2 font-mono text-[12px] tabular font-semibold ${t.pnl_usd > 0 ? "text-[var(--green-bright)]" : t.pnl_usd < 0 ? "text-[var(--red)]" : "text-[var(--text-dim)]"}`}
                                        >
                                            {t.pnl_usd >= 0 ? "+" : ""}$
                                            {t.pnl_usd.toFixed(2)}
                                        </td>
                                        <td
                                            className={`px-3 py-2 font-mono text-[12px] tabular ${t.r_multiple > 0 ? "text-[var(--green-bright)]" : t.r_multiple < 0 ? "text-[var(--red)]" : "text-[var(--text-dim)]"}`}
                                        >
                                            {t.r_multiple >= 0 ? "+" : ""}
                                            {t.r_multiple.toFixed(2)}R
                                        </td>
                                        <td className="px-3 py-2">
                                            <span
                                                className={`kicker px-1.5 py-0.5 border ${
                                                    t.status === "open"
                                                        ? "text-[var(--amber)] border-[var(--amber)]"
                                                        : t.status ===
                                                            "closed-win"
                                                          ? "text-[var(--green-bright)] border-[var(--green)]"
                                                          : t.status ===
                                                              "closed-loss"
                                                            ? "text-[var(--red)] border-[var(--red)]"
                                                            : "text-[var(--text-dim)] border-[var(--border)]"
                                                }`}
                                            >
                                                {t.status}
                                            </span>
                                        </td>
                                        <td className="px-3 py-2">
                                            <button
                                                type="button"
                                                onClick={() => remove(t.id)}
                                                className="text-[var(--text-faint)] hover:text-[var(--red)] transition-colors"
                                                data-testid={`delete-trade-${t.id}`}
                                                title="Borrar"
                                            >
                                                <Trash2 size={13} />
                                            </button>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </section>
    );
}
