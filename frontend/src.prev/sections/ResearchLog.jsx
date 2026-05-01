/**
 * ResearchLog — per-trade research record visualisation.
 *
 * Pulls /api/research/trades and renders one expandable card per trade
 * with: scoring breakdown, SL/TP/exit, MAE/MFE, BE/trail events, exit
 * reason, R-multiple. This is the post-test feedback view for figuring
 * out what worked and what didn't.
 */
import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { ChevronDown, ChevronRight, FileSearch, Target, TrendingUp, TrendingDown, Lock, Activity } from "lucide-react";

const SCORE_COMPONENTS = [
    { key: "trend_m15", label: "Tend. M15",   max: 15 },
    { key: "trend_h4",  label: "Tend. H4",    max: 15 },
    { key: "trend_d1",  label: "Tend. D1",    max: 15 },
    { key: "momentum_rsi", label: "Momentum", max: 10 },
    { key: "volume",    label: "Volumen",     max: 10 },
    { key: "swing",     label: "Swing",       max: 10 },
    { key: "rr",        label: "R/R",         max: 10 },
    { key: "atr",       label: "ATR",         max: 10 },
    { key: "room",      label: "Espacio",     max: 5 },
];

const REASON_LABEL = {
    SL_HIT:           { es: "SL alcanzado",       color: "text-[var(--red)]" },
    TRAILING_SL:      { es: "Trailing SL",        color: "text-[var(--amber)]" },
    TP_HIT:           { es: "TP alcanzado",       color: "text-[var(--green-bright)]" },
    TRAILING_TP:      { es: "Trailing TP",        color: "text-[var(--green-bright)]" },
    EARLY_TAKE:       { es: "Cierre temprano",    color: "text-[var(--amber)]" },
    MANUAL_OR_EARLY:  { es: "Manual o anticipado", color: "text-[var(--text-dim)]" },
    UNKNOWN:          { es: "Desconocido",        color: "text-[var(--text-faint)]" },
};

function fmtTime(iso) {
    if (!iso) return "—";
    try {
        return new Date(iso).toLocaleString("es-ES", {
            day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
        });
    } catch { return iso; }
}

function fmtDuration(s) {
    if (s == null) return "—";
    if (s < 60) return `${s}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

function ScoreBars({ breakdown }) {
    if (!breakdown) return null;
    return (
        <div className="grid grid-cols-3 md:grid-cols-9 gap-1 mt-2">
            {SCORE_COMPONENTS.map(({ key, label, max }) => {
                const v = Number(breakdown[key]);
                const filled = Number.isFinite(v) ? Math.max(0, Math.min(v, max)) : 0;
                const got = filled === max ? "var(--green)"
                            : filled > 0   ? "var(--amber)"
                            : "var(--border)";
                return (
                    <div key={key} title={`${label}: ${filled} / ${max}`}
                         className="flex flex-col items-center">
                        <div className="w-full h-2 bg-[var(--bg)] border border-[var(--border)] rounded-sm overflow-hidden">
                            <div className="h-full"
                                 style={{ background: got, width: `${(filled / max) * 100}%` }} />
                        </div>
                        <div className="kicker text-[9px] mt-1 text-[var(--text-faint)] text-center leading-tight">
                            {label}
                        </div>
                        <div className="font-mono text-[10px] tabular text-[var(--text)]">
                            {filled}/{max}
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

function TradeCard({ trade }) {
    const [open, setOpen] = useState(false);
    const o = trade.open || {};
    const c = trade.close || null;
    const m = trade.manage || [];
    const breakdown = o.breakdown || {};
    const ctx = o.context || {};
    const cfg = o.config || {};

    const symbol = o.symbol || c?.symbol || "—";
    const side = o.side || c?.side;
    const score = o.score;
    const isOpen = !c;
    const pnl = c?.pnl_usd;
    const r = c?.r_multiple;
    const reason = c?.exit_reason || "—";
    const reasonObj = REASON_LABEL[reason] || REASON_LABEL.UNKNOWN;

    const pnlColor = pnl == null ? "text-[var(--text-faint)]"
                  : pnl > 0 ? "text-[var(--green-bright)]"
                  : pnl < 0 ? "text-[var(--red)]"
                  : "text-[var(--text)]";

    return (
        <div className={`panel mb-2 ${isOpen ? "border-[var(--amber)]" : ""}`}
             data-testid={`research-trade-${trade.ticket}`}>
            {/* Header — clickable */}
            <button
                onClick={() => setOpen(!open)}
                className="w-full flex items-center gap-3 p-3 hover:bg-[var(--surface-2)] transition-colors text-left"
            >
                {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <div className="font-mono text-[11px] text-[var(--text-faint)] tabular w-32 flex-shrink-0">
                    {fmtTime(o.ts || c?.ts)}
                </div>
                <div className="font-display font-semibold text-sm w-20">
                    {symbol}
                </div>
                <div className={`text-xs font-mono px-2 py-0.5 border w-20 text-center ${
                    side === "buy"
                        ? "border-[var(--green)] text-[var(--green-bright)]"
                        : "border-[var(--red)] text-[var(--red)]"
                }`}>
                    {side === "buy" ? "compra" : side === "sell" ? "venta" : "—"}
                </div>
                <div className="text-xs font-mono w-16 text-center">
                    score <span className={
                        score >= 70 ? "text-[var(--green-bright)] font-bold"
                        : score >= 50 ? "text-[var(--amber)]"
                        : "text-[var(--text-dim)]"
                    }>{score ?? "—"}</span>
                </div>
                <div className={`font-mono text-sm tabular w-24 text-right ${pnlColor}`}>
                    {pnl == null ? "abierto…" : `${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}`}
                </div>
                <div className="font-mono text-[11px] tabular w-16 text-right text-[var(--text-dim)]">
                    {r != null ? `${r >= 0 ? "+" : ""}${r.toFixed(2)}R` : ""}
                </div>
                <div className={`text-[10px] font-mono ml-2 ${reasonObj.color}`}>
                    {isOpen ? "" : reasonObj.es}
                </div>
            </button>

            {/* Expanded details */}
            {open && (
                <div className="border-t border-[var(--border)] p-4 text-xs">
                    {/* Setup snapshot */}
                    <div className="mb-4">
                        <div className="kicker mb-2 flex items-center gap-2">
                            <Target size={11} /> Setup al momento de abrir
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 font-mono">
                            <div>
                                <div className="kicker text-[var(--text-faint)]">Entry</div>
                                <div className="tabular">{o.entry ?? "—"}</div>
                            </div>
                            <div>
                                <div className="kicker text-[var(--text-faint)]">SL</div>
                                <div className="tabular text-[var(--red)]">{o.sl ?? "—"}</div>
                            </div>
                            <div>
                                <div className="kicker text-[var(--text-faint)]">TP</div>
                                <div className="tabular text-[var(--green-bright)]">{o.tp ?? "—"}</div>
                            </div>
                            <div>
                                <div className="kicker text-[var(--text-faint)]">ATR</div>
                                <div className="tabular">{o.atr ?? "—"}</div>
                            </div>
                            <div>
                                <div className="kicker text-[var(--text-faint)]">Lots</div>
                                <div className="tabular">{o.lots ?? "—"}</div>
                            </div>
                            <div>
                                <div className="kicker text-[var(--text-faint)]">Riesgo $</div>
                                <div className="tabular">${o.risk_usd?.toFixed?.(2) ?? "—"}</div>
                            </div>
                            <div>
                                <div className="kicker text-[var(--text-faint)]">Score / Rec</div>
                                <div className="tabular">{score ?? "—"} · {o.rec ?? "—"}</div>
                            </div>
                            <div>
                                <div className="kicker text-[var(--text-faint)]">Hora UTC</div>
                                <div className="tabular">
                                    {ctx.utc_hour != null ? `${String(ctx.utc_hour).padStart(2, "0")}:${String(ctx.utc_minute || 0).padStart(2, "0")}` : "—"}
                                </div>
                            </div>
                        </div>
                        <ScoreBars breakdown={breakdown} />
                    </div>

                    {/* Context */}
                    <div className="mb-4">
                        <div className="kicker mb-2 flex items-center gap-2">
                            <Activity size={11} /> Contexto
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 font-mono text-[11px]">
                            <div>
                                <div className="kicker text-[var(--text-faint)]">Saldo @ entry</div>
                                <div className="tabular">${ctx.balance_at_entry?.toFixed?.(2) ?? "—"}</div>
                            </div>
                            <div>
                                <div className="kicker text-[var(--text-faint)]">Trades hoy (antes)</div>
                                <div className="tabular">{ctx.trades_today_before ?? "—"}</div>
                            </div>
                            <div>
                                <div className="kicker text-[var(--text-faint)]">Pérdidas seguidas</div>
                                <div className={`tabular ${ctx.consecutive_losses_today >= 2 ? "text-[var(--amber)]" : ""}`}>
                                    {ctx.consecutive_losses_today ?? 0}
                                </div>
                            </div>
                            <div>
                                <div className="kicker text-[var(--text-faint)]">min_score / interval</div>
                                <div className="tabular">{cfg.min_score ?? "—"} / {cfg.interval_s ?? "—"}s</div>
                            </div>
                        </div>
                    </div>

                    {/* Manage events */}
                    {m.length > 0 && (
                        <div className="mb-4">
                            <div className="kicker mb-2 flex items-center gap-2">
                                <Lock size={11} /> Eventos de gestión ({m.length})
                            </div>
                            <div className="space-y-1 font-mono text-[11px]">
                                {m.map((ev, i) => (
                                    <div key={i} className="flex items-center gap-2 text-[var(--text-dim)]">
                                        <span className="text-[var(--text-faint)] w-12">{fmtTime(ev.ts)?.slice(-5)}</span>
                                        <span className={ev.action === "breakeven" ? "text-[var(--amber)]" : "text-[var(--green)]"}>
                                            {ev.action === "breakeven" ? "🔒 BE" : "📈 trail"}
                                        </span>
                                        <span>SL {ev.old_sl} → {ev.new_sl}</span>
                                        <span className="text-[var(--text-faint)]">@ {ev.current_price} (R={ev.rr_progress})</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Close summary */}
                    {c && (
                        <div>
                            <div className="kicker mb-2 flex items-center gap-2">
                                {pnl >= 0 ? <TrendingUp size={11} className="text-[var(--green)]" />
                                          : <TrendingDown size={11} className="text-[var(--red)]" />}
                                Resultado
                            </div>
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 font-mono text-[11px]">
                                <div>
                                    <div className="kicker text-[var(--text-faint)]">Exit price</div>
                                    <div className="tabular">{c.exit ?? "—"}</div>
                                </div>
                                <div>
                                    <div className="kicker text-[var(--text-faint)]">Razón</div>
                                    <div className={reasonObj.color}>{reasonObj.es}</div>
                                </div>
                                <div>
                                    <div className="kicker text-[var(--text-faint)]">Duración</div>
                                    <div className="tabular">{fmtDuration(c.duration_seconds)}</div>
                                </div>
                                <div>
                                    <div className="kicker text-[var(--text-faint)]">BE / trails</div>
                                    <div className="tabular">{c.be_moved ? "sí" : "no"} / {c.trail_count ?? 0}</div>
                                </div>
                                <div>
                                    <div className="kicker text-[var(--text-faint)]">MFE</div>
                                    <div className="tabular text-[var(--green)]">+{c.mfe_r?.toFixed?.(2) ?? 0}R</div>
                                </div>
                                <div>
                                    <div className="kicker text-[var(--text-faint)]">MAE</div>
                                    <div className="tabular text-[var(--red)]">{c.mae_r?.toFixed?.(2) ?? 0}R</div>
                                </div>
                                <div>
                                    <div className="kicker text-[var(--text-faint)]">SL/TP originales</div>
                                    <div className="tabular text-[10px]">{c.original_sl} / {c.original_tp}</div>
                                </div>
                                <div>
                                    <div className="kicker text-[var(--text-faint)]">PnL · R</div>
                                    <div className={`tabular ${pnlColor} font-bold`}>
                                        {pnl >= 0 ? "+" : ""}${pnl?.toFixed?.(2)} · {r >= 0 ? "+" : ""}{r?.toFixed?.(2)}R
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

export default function ResearchLog({ api }) {
    const [data, setData] = useState({ trades: [], total: 0 });

    const refresh = useCallback(async () => {
        try {
            const r = await axios.get(`${api}/research/trades?limit=100`);
            setData(r.data || { trades: [], total: 0 });
        } catch {
            // silent
        }
    }, [api]);

    useEffect(() => {
        refresh();
        const id = setInterval(refresh, 8000);
        return () => clearInterval(id);
    }, [refresh]);

    const trades = data.trades || [];
    return (
        <div className="panel p-5 mb-3" data-testid="research-log">
            <div className="flex items-center justify-between mb-4">
                <div className="kicker flex items-center gap-2">
                    <FileSearch size={14} className="text-[var(--blue)]" />
                    Investigación por trade · feedback para post-test
                </div>
                <div className="text-[10px] font-mono text-[var(--text-faint)]">
                    {trades.length} de {data.total} mostrados
                </div>
            </div>

            {trades.length === 0 ? (
                <div className="text-[var(--text-dim)] text-sm font-mono py-4">
                    Sin trades registrados todavía. El bot escribe a este log cada vez que abre,
                    gestiona (BE/trail) o cierra una posición. Los trades anteriores al lanzamiento
                    de esta función no aparecerán — sólo los nuevos.
                </div>
            ) : (
                <div className="text-xs">
                    {/* Header row */}
                    <div className="flex items-center gap-3 px-3 py-1 text-[10px] font-mono text-[var(--text-faint)] border-b border-[var(--border)] mb-2">
                        <div className="w-[14px]"></div>
                        <div className="w-32">Hora</div>
                        <div className="w-20">Símbolo</div>
                        <div className="w-20">Lado</div>
                        <div className="w-16 text-center">Score</div>
                        <div className="w-24 text-right">PnL</div>
                        <div className="w-16 text-right">R</div>
                        <div className="ml-2">Razón</div>
                    </div>
                    {trades.map((t) => (
                        <TradeCard key={t.ticket} trade={t} />
                    ))}
                </div>
            )}
        </div>
    );
}
