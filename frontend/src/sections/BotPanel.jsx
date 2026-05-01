import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
    Eye,
    Radio,
    Send,
    Settings,
    Terminal,
    PlayCircle,
    CheckCircle2,
    Sparkles,
} from "lucide-react";

const TOKEN = process.env.REACT_APP_DASHBOARD_TOKEN || "";
const authHeaders = TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};

const SCORE_COLOR = (s) =>
    s >= 70
        ? "text-[var(--green-bright)]"
        : s >= 50
          ? "text-[var(--amber)]"
          : "text-[var(--text-dim)]";

const REC_COLOR = (r) =>
    r === "TAKE"
        ? "text-[var(--green-bright)]"
        : r === "WAIT"
          ? "text-[var(--amber)]"
          : "text-[var(--red)]";


const BREAKDOWN_LABELS = {
    trend_m15:    "Tendencia M15",
    trend_h4:     "Tendencia H4",
    trend_d1:     "Tendencia diaria",
    momentum_rsi: "Momentum (RSI)",
    volume:       "Volumen",
    swing:        "Swing reciente",
    rr:           "Riesgo/Recompensa",
    atr:          "Volatilidad",
    room:         "Espacio para correr",
    // legacy v1 keys (kept so old scans still render)
    trend:        "Tendencia",
    mtf:          "Multi-timeframe",
    sr:           "Soporte/Resistencia",
    pattern:      "Patrón de vela",
    rsi:          "RSI no extremo",
};


function BreakdownChips({ breakdown }) {
    if (!breakdown) return null;
    const entries = Object.entries(breakdown).filter(([, v]) => typeof v === "number");
    if (!entries.length) return null;
    return (
        <div className="flex flex-wrap gap-2 mt-3">
            {entries.map(([k, v]) => (
                <div
                    key={k}
                    className={`text-[10px] font-mono px-2 py-1 border ${
                        v > 0
                            ? "border-[var(--green)] text-[var(--green-bright)]"
                            : "border-[var(--border)] text-[var(--text-faint)]"
                    }`}
                >
                    {BREAKDOWN_LABELS[k] || k}{" "}
                    <span className={v > 0 ? "font-bold" : ""}>+{v}</span>
                </div>
            ))}
        </div>
    );
}


function ScanTable({ candidates }) {
    if (!candidates || candidates.length === 0) {
        return (
            <div className="text-[var(--text-dim)] text-sm font-mono py-3">
                Sin escaneo aún. Pulsa "Buscar setups ahora" para el primer
                resultado.
            </div>
        );
    }
    return (
        <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono tabular">
                <thead>
                    <tr className="text-[var(--text-faint)] border-b border-[var(--border)]">
                        <th className="text-left py-2">Símbolo</th>
                        <th className="text-left py-2">Lado</th>
                        <th className="text-right py-2">Score</th>
                        <th className="text-right py-2">Decisión</th>
                        <th className="text-right py-2">Entry</th>
                        <th className="text-right py-2">SL</th>
                        <th className="text-right py-2">TP</th>
                    </tr>
                </thead>
                <tbody>
                    {candidates.map((c, i) => {
                        if (c.status) {
                            return (
                                <tr key={i} className="border-b border-[var(--border)]">
                                    <td className="py-2.5">{c.symbol}</td>
                                    <td colSpan={6} className="py-2.5 text-[var(--text-faint)]">
                                        {c.status}
                                    </td>
                                </tr>
                            );
                        }
                        if (c.error) {
                            return (
                                <tr key={i} className="border-b border-[var(--border)]">
                                    <td className="py-2.5">{c.symbol}</td>
                                    <td colSpan={6} className="py-2.5 text-[var(--red)]">
                                        error: {c.error}
                                    </td>
                                </tr>
                            );
                        }
                        return (
                            <tr key={i} className="border-b border-[var(--border)]">
                                <td className="py-2.5">{c.symbol}</td>
                                <td className="py-2.5">
                                    <span className={c.side === "buy" ? "text-[var(--green)]" : "text-[var(--red)]"}>
                                        {c.side === "buy" ? "Compra" : "Venta"}
                                    </span>
                                </td>
                                <td className={`py-2.5 text-right font-bold ${SCORE_COLOR(c.score)}`}>
                                    {c.score}
                                </td>
                                <td className={`py-2.5 text-right ${REC_COLOR(c.rec)}`}>
                                    {c.rec === "TAKE" ? "TOMAR" : c.rec === "WAIT" ? "ESPERAR" : "SALTAR"}
                                </td>
                                <td className="py-2.5 text-right">{c.entry}</td>
                                <td className="py-2.5 text-right text-[var(--red)]">{c.sl}</td>
                                <td className="py-2.5 text-right text-[var(--green)]">{c.tp}</td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}


function ManualTradeForm({ api, onSubmitted }) {
    const [form, setForm] = useState({
        symbol: "EURUSD", side: "buy", sl: "", tp: "", risk_pct: 1.0,
    });
    const [loading, setLoading] = useState(false);

    const submit = async () => {
        if (!form.sl || !form.tp) {
            toast.error("Stop Loss y Take Profit son obligatorios");
            return;
        }
        if (!window.confirm(`Ejecutar ${form.side === "buy" ? "compra" : "venta"} de ${form.symbol}? SL=${form.sl}, TP=${form.tp}, riesgo=${form.risk_pct}%`)) {
            return;
        }
        try {
            setLoading(true);
            const r = await axios.post(
                `${api}/bot/execute`,
                {
                    symbol: form.symbol.toUpperCase(),
                    side: form.side,
                    sl: parseFloat(form.sl),
                    tp: parseFloat(form.tp),
                    risk_pct: parseFloat(form.risk_pct),
                },
                { headers: authHeaders, timeout: 60000 },
            );
            const result = r.data?.result;
            if (result?.ok) {
                toast.success(`Orden enviada · ticket ${result.ticket} · ${result.mode}`);
                onSubmitted?.();
            } else {
                toast.error(`Rechazada: ${result?.reason || r.data?.reason} — ${result?.detail || r.data?.detail || ""}`);
            }
        } catch (e) {
            toast.error(`Error: ${e.response?.data?.detail || e.message}`);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            <div>
                <div className="kicker text-[var(--text-faint)] mb-1">Símbolo</div>
                <input
                    className="input-sharp"
                    value={form.symbol}
                    onChange={(e) => setForm({ ...form, symbol: e.target.value })}
                    data-testid="manual-symbol"
                />
            </div>
            <div>
                <div className="kicker text-[var(--text-faint)] mb-1">Lado</div>
                <select
                    className="input-sharp"
                    value={form.side}
                    onChange={(e) => setForm({ ...form, side: e.target.value })}
                    data-testid="manual-side"
                >
                    <option value="buy">Compra</option>
                    <option value="sell">Venta</option>
                </select>
            </div>
            <div>
                <div className="kicker text-[var(--text-faint)] mb-1">Stop Loss</div>
                <input
                    className="input-sharp"
                    type="number"
                    step="0.00001"
                    placeholder="ej. 1.0830"
                    value={form.sl}
                    onChange={(e) => setForm({ ...form, sl: e.target.value })}
                    data-testid="manual-sl"
                />
            </div>
            <div>
                <div className="kicker text-[var(--text-faint)] mb-1">Take Profit</div>
                <input
                    className="input-sharp"
                    type="number"
                    step="0.00001"
                    placeholder="ej. 1.0890"
                    value={form.tp}
                    onChange={(e) => setForm({ ...form, tp: e.target.value })}
                    data-testid="manual-tp"
                />
            </div>
            <div>
                <div className="kicker text-[var(--text-faint)] mb-1">Riesgo %</div>
                <input
                    className="input-sharp"
                    type="number"
                    step="0.1"
                    min="0.1"
                    max="2"
                    value={form.risk_pct}
                    onChange={(e) => setForm({ ...form, risk_pct: e.target.value })}
                    data-testid="manual-risk"
                />
            </div>
            <div className="col-span-2 lg:col-span-5">
                <button
                    onClick={submit}
                    disabled={loading}
                    className="btn-sharp primary flex items-center gap-2"
                    data-testid="manual-execute"
                >
                    <Send size={14} />
                    {loading ? "Enviando…" : "Ejecutar orden"}
                </button>
                <span className="ml-3 text-[11px] text-[var(--text-faint)] font-mono">
                    Pasa por todas las reglas de seguridad. Lotaje se calcula
                    automáticamente.
                </span>
            </div>
        </div>
    );
}


export default function BotPanel({ api, onMutated }) {
    const [scan, setScan] = useState(null);
    const [scanLoading, setScanLoading] = useState(false);
    const [acceptLoading, setAcceptLoading] = useState(false);
    const [botStatus, setBotStatus] = useState(null);
    const [logs, setLogs] = useState([]);
    const [config, setConfig] = useState(null);

    const refresh = useCallback(async () => {
        try {
            const [s, l, c] = await Promise.all([
                axios.get(`${api}/bot/status`),
                axios.get(`${api}/bot/log?n=15`),
                axios.get(`${api}/bot/config`),
            ]);
            setBotStatus(s.data);
            setLogs(l.data.events || []);
            setConfig(c.data);
            if (s.data.last_scan) {
                setScan(s.data.last_scan);
            }
        } catch (e) {
            console.error("bot panel refresh", e);
        }
    }, [api]);

    useEffect(() => {
        refresh();
        const id = setInterval(refresh, 8000);
        return () => clearInterval(id);
    }, [refresh]);

    const acceptBest = async () => {
        const best = scan?.best;
        if (!best || best.score < 70) return;
        const sideEs = best.side === "buy" ? "compra" : "venta";
        if (!window.confirm(
            `Tomar la sugerencia del bot?\n\n` +
            `${best.symbol} · ${sideEs}\n` +
            `Entrada ${best.entry}\n` +
            `Stop Loss ${best.sl}\n` +
            `Take Profit ${best.tp}\n` +
            `Score ${best.score} / 100\n\n` +
            `Pasará por las mismas reglas de seguridad que el bot.`
        )) return;
        try {
            setAcceptLoading(true);
            const r = await axios.post(
                `${api}/bot/execute`,
                {
                    symbol: best.symbol,
                    side: best.side,
                    sl: best.sl,
                    tp: best.tp,
                    risk_pct: 1.0,
                },
                { headers: authHeaders, timeout: 60000 },
            );
            const result = r.data?.result;
            if (result?.ok) {
                toast.success(
                    `Orden colocada · ${best.symbol} ${sideEs} · ticket ${result.ticket}`
                );
                // OPTIMISTIC UPDATE: incrementar open_count localmente para
                // que el botón se deshabilite inmediatamente (evita doble-click
                // race window de hasta 8s entre el OK y el siguiente refresh).
                setBotStatus((prev) => ({
                    ...(prev || {}),
                    open_count: (prev?.open_count ?? 0) + 1,
                    open_symbols: [...(prev?.open_symbols || []), best.symbol],
                }));
                onMutated?.();
                refresh();
            } else {
                toast.error(
                    `Rechazada: ${result?.reason || r.data?.reason} — ${result?.detail || r.data?.detail || ""}`
                );
            }
        } catch (e) {
            toast.error(`Error: ${e.response?.data?.detail || e.message}`);
        } finally {
            setAcceptLoading(false);
        }
    };

    const triggerScan = async () => {
        try {
            setScanLoading(true);
            const r = await axios.post(`${api}/bot/scan`, {}, {
                headers: authHeaders, timeout: 60000,
            });
            if (r.data?.ok) {
                setScan({
                    ts: new Date().toISOString(),
                    best: r.data.best,
                    candidates: r.data.candidates,
                });
                if (r.data.best && r.data.best.score >= 70) {
                    toast.success(`Setup encontrado: ${r.data.best.symbol} ${r.data.best.side === "buy" ? "compra" : "venta"} (score ${r.data.best.score})`);
                } else {
                    toast.success("Escaneo completo. Sin setups con score ≥70.");
                }
                onMutated?.();
            } else {
                toast.error(`Escaneo falló: ${r.data?.reason}`);
            }
        } catch (e) {
            toast.error(`Error: ${e.message}`);
        } finally {
            setScanLoading(false);
        }
    };

    const formatTs = (s) => {
        if (!s) return "—";
        return new Date(s).toLocaleTimeString("es-ES");
    };

    return (
        <>
            {/* Bot status banner */}
            <div className="panel mb-4 px-5 py-4 flex items-center justify-between flex-wrap gap-3">
                <div className="flex items-center gap-3">
                    <Radio
                        size={16}
                        className={botStatus?.alive ? "text-[var(--green-bright)]" : "text-[var(--text-faint)]"}
                    />
                    <div>
                        <div className="kicker">
                            {botStatus?.alive ? "BOT EN VIVO" : "BOT INACTIVO"}
                        </div>
                        <div className="text-[11px] font-mono text-[var(--text-dim)] mt-1">
                            {botStatus?.alive
                                ? `Última actividad: ${formatTs(botStatus.last_iter_ts)} · Trades abiertos: ${botStatus.open_count} · Cerrados: ${botStatus.closed_count}`
                                : "El proceso del bot no se ha detectado en los últimos 5 minutos."}
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-4">
                    {botStatus && (
                        <div className="flex gap-6 text-xs font-mono">
                            <div>
                                <div className="kicker text-[var(--text-faint)]">Aciertos</div>
                                <div className="text-[var(--green-bright)] tabular">
                                    {botStatus.wins}
                                </div>
                            </div>
                            <div>
                                <div className="kicker text-[var(--text-faint)]">Fallos</div>
                                <div className="text-[var(--red)] tabular">
                                    {botStatus.losses}
                                </div>
                            </div>
                            <div>
                                <div className="kicker text-[var(--text-faint)]">P&L total</div>
                                <div className={`tabular ${botStatus.total_pnl_usd >= 0 ? "text-[var(--green-bright)]" : "text-[var(--red)]"}`}>
                                    {botStatus.total_pnl_usd >= 0 ? "+" : ""}${botStatus.total_pnl_usd}
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* What the bot sees */}
            <div className="panel p-5 mb-4" data-testid="card-scan">
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                        <Eye size={16} className="text-[var(--blue)]" />
                        <span className="kicker">Lo que ve el bot</span>
                    </div>
                    <div className="flex items-center gap-3">
                        {scan?.ts && (
                            <span className="kicker text-[var(--text-faint)]">
                                Último: {formatTs(scan.ts)}
                            </span>
                        )}
                        <button
                            onClick={triggerScan}
                            disabled={scanLoading}
                            className="btn-sharp primary flex items-center gap-2"
                            data-testid="scan-now"
                        >
                            <PlayCircle size={14} />
                            {scanLoading ? "Buscando…" : "Buscar setups ahora"}
                        </button>
                    </div>
                </div>
                <ScanTable candidates={scan?.candidates} />
                {scan?.best && scan.best.score >= 70 && (
                    <div className="mt-4 panel p-4 stripes-warn" data-testid="best-setup">
                        <div className="flex items-start justify-between gap-4 flex-wrap">
                            <div className="flex-1 min-w-[300px]">
                                <div className="flex items-center gap-2 mb-2">
                                    <Sparkles size={14} className="text-[var(--green-bright)]" />
                                    <span className="kicker text-[var(--green-bright)]">
                                        Sugerencia del bot · acción recomendada
                                    </span>
                                </div>
                                <div className="font-display text-xl font-bold mb-2">
                                    <span className="text-white">{scan.best.symbol}</span>{" "}
                                    <span className={scan.best.side === "buy" ? "text-[var(--green-bright)]" : "text-[var(--red)]"}>
                                        {scan.best.side === "buy" ? "COMPRA" : "VENTA"}
                                    </span>
                                    <span className="text-[var(--text-faint)] text-sm font-mono ml-3">
                                        score {scan.best.score} / 100
                                    </span>
                                </div>
                                <div className="grid grid-cols-3 gap-3 text-xs font-mono mt-2">
                                    <div>
                                        <div className="kicker text-[var(--text-faint)]">Entrada</div>
                                        <div className="tabular mt-1">{scan.best.entry}</div>
                                    </div>
                                    <div>
                                        <div className="kicker text-[var(--text-faint)]">Stop Loss</div>
                                        <div className="tabular text-[var(--red)] mt-1">{scan.best.sl}</div>
                                    </div>
                                    <div>
                                        <div className="kicker text-[var(--text-faint)]">Take Profit</div>
                                        <div className="tabular text-[var(--green-bright)] mt-1">{scan.best.tp}</div>
                                    </div>
                                </div>
                                <BreakdownChips breakdown={scan.best.breakdown} />
                                <div className="text-[10px] text-[var(--text-faint)] font-mono mt-3">
                                    Riesgo {1}% del balance · lotaje calculado automáticamente · todas las reglas se aplican
                                </div>
                            </div>
                            <div className="flex flex-col gap-2 min-w-[180px]">
                                <button
                                    onClick={acceptBest}
                                    disabled={acceptLoading || (botStatus?.open_count ?? 0) > 0}
                                    className="btn-sharp primary flex items-center justify-center gap-2 py-3"
                                    data-testid="accept-best"
                                    title={(botStatus?.open_count ?? 0) > 0
                                        ? "Ya tienes una posición abierta"
                                        : "Tomar este setup ahora"}
                                >
                                    <CheckCircle2 size={16} />
                                    {acceptLoading ? "Enviando…" : "Aceptar y operar"}
                                </button>
                                {(botStatus?.open_count ?? 0) > 0 && (
                                    <div className="text-[10px] text-[var(--amber)] font-mono text-center">
                                        Ya tienes una posición abierta. Espera al cierre.
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {/* Manual trade */}
            <div className="panel p-5 mb-4">
                <div className="flex items-center gap-2 mb-3">
                    <Send size={16} className="text-[var(--amber)]" />
                    <span className="kicker">Operar manualmente</span>
                </div>
                <p className="text-xs text-[var(--text-dim)] mb-4">
                    Ejecuta un trade manual con las mismas reglas de seguridad
                    del bot. El lotaje se calcula automáticamente desde el SL.
                </p>
                <ManualTradeForm api={api} onSubmitted={refresh} />
            </div>

            {/* Config */}
            <div className="panel p-5 mb-4">
                <div className="flex items-center gap-2 mb-3">
                    <Settings size={16} className="text-[var(--text-dim)]" />
                    <span className="kicker">Configuración del bot</span>
                </div>
                {config ? (
                    <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 text-xs font-mono">
                        {[
                            ["TRADING_MODE", "Modo"],
                            ["MT5_LOGIN", "Cuenta"],
                            ["MT5_SERVER", "Servidor"],
                            ["MAX_LOTS_PER_TRADE", "Lots máx."],
                            ["MT5_MAGIC", "Magic ID"],
                            ["DASHBOARD_URL", "Backend URL"],
                        ].map(([k, label]) => (
                            <div key={k}>
                                <div className="kicker text-[var(--text-faint)] mb-1">{label}</div>
                                <div className="text-[var(--text-dim)] truncate">
                                    {config[k] || "—"}
                                </div>
                            </div>
                        ))}
                    </div>
                ) : (
                    <div className="text-[var(--text-dim)] text-sm">Cargando…</div>
                )}
            </div>

            {/* Live log */}
            <div className="panel p-5">
                <div className="flex items-center gap-2 mb-3">
                    <Terminal size={16} className="text-[var(--text-faint)]" />
                    <span className="kicker">Actividad reciente del bot</span>
                </div>
                {logs.length === 0 ? (
                    <div className="text-[var(--text-dim)] text-sm">
                        Sin actividad registrada todavía.
                    </div>
                ) : (
                    <div className="font-mono text-[11px] space-y-1 max-h-[300px] overflow-y-auto codeblock">
                        {logs.slice().reverse().map((e, i) => {
                            let line = formatTs(e.ts) + " · ";
                            if (e.event === "start") {
                                line += `▶ inicio interval=${e.interval}s riesgo=${e.risk_pct}%`;
                            } else if (e.event === "stop") {
                                line += `■ parado · ${e.iterations} iteraciones`;
                            } else if (e.skip === "OPEN_POSITION") {
                                line += `⏸ posición abierta — esperando`;
                            } else if (e.skip === "HALTED") {
                                line += `🛑 HALT — ${e.reason}`;
                            } else if (e.skip === "MT5_DISCONNECTED") {
                                line += `⚠ MT5 desconectado`;
                            } else if (e.skip === "NO_BALANCE") {
                                line += `💰 sin saldo (${e.balance})`;
                            } else if (e.skip === "SIZE_ZERO") {
                                line += `🚫 lotaje 0 — riesgo bajo el mínimo`;
                            } else if (e.phase === "scan") {
                                line += `🔍 escaneo · mejor score=${e.best_score} · balance=$${e.balance}`;
                            } else if (e.phase === "order") {
                                const ok = e.result?.ok;
                                line += ok ? `✅ orden colocada ${e.best?.symbol} ${e.best?.side}` : `❌ rechazada: ${e.result?.reason}`;
                            } else if (e.phase === "close") {
                                const t = e.trade;
                                line += `${t?.status === "closed-win" ? "🟢" : "🔴"} cierre ${t?.symbol} ${t?.exit_reason} · pnl=$${t?.pnl_usd} · ${t?.r_multiple}R`;
                            } else if (e.error) {
                                line += `❗ error: ${e.error}`;
                            } else {
                                line += JSON.stringify(e);
                            }
                            return (
                                <div key={i} className="text-[var(--text-dim)]">
                                    {line}
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </>
    );
}
