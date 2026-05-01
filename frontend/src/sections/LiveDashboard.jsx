/**
 * LiveDashboard — the new "above the fold" hero panel.
 *
 * Shows everything you need to know at a glance:
 *   - Equity headline with mini sparkline (last ~5 min of equity samples)
 *   - Today's P&L percentage with a progress arc
 *   - Active position visualised on a price scale (SL ─ entry ─ current ─ TP)
 *   - Bot loop heartbeat (alive + last scan + best candidate score)
 *   - Discipline gauge (rule-adherence over last 30 trades)
 *
 * Data comes from polling four backend endpoints every 3s — no websockets,
 * dumb-simple, robust against backend restarts.
 */
import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
    LineChart,
    Line,
    YAxis,
    Tooltip,
    ResponsiveContainer,
    ReferenceLine,
} from "recharts";
import { Cpu, Wallet, ShieldCheck, AlertTriangle, Pause, Radio, Activity,  } from "lucide-react";
import { apiGet } from "@/lib/api";

const TICK_MS = 3000;
const MAX_SAMPLES = 1000;         // ~hasta 24h cuando se siembra de /api/equity/samples

const fmtMoney = (v, fr = 2) =>
    typeof v === "number" && Number.isFinite(v)
        ? `$${v.toLocaleString("en-US", { minimumFractionDigits: fr, maximumFractionDigits: fr })}`
        : "—";

const fmtPct = (v, fr = 2) =>
    typeof v === "number" && Number.isFinite(v)
        ? `${v >= 0 ? "+" : ""}${v.toFixed(fr)}%`
        : "—";

const timeAgo = (iso) => {
    if (!iso) return "—";
    try {
        const t = typeof iso === "string" ? new Date(iso).getTime() : iso;
        const sec = Math.floor((Date.now() - t) / 1000);
        if (sec < 0) return "ahora";
        if (sec < 60) return `${sec}s`;
        if (sec < 3600) return `${Math.floor(sec / 60)}m`;
        if (sec < 86400) return `${Math.floor(sec / 3600)}h`;
        return `${Math.floor(sec / 86400)}d`;
    } catch {
        return "—";
    }
};

// --------------------------------------------------------------------------
// EquityHero — big number + sparkline
// --------------------------------------------------------------------------
function EquityHero({ samples, balance, equity, todayPct, dailyCapPct }) {
    const baseline = samples.length > 0 ? samples[0].equity : balance;
    const latest = equity ?? baseline;
    const change = latest - baseline;
    const changePct = baseline > 0 ? (change / baseline) * 100 : 0;
    const up = change >= 0;
    const data = samples.length > 1 ? samples : [
        { t: 0, equity: baseline },
        { t: 1, equity: latest },
    ];

    // Sublabel: "desde {fecha del primer sample}" — muestra que la serie es
    // persistida desde que el bot arrancó, no desde que abriste el tab.
    const firstTs = samples.length > 0 ? samples[0].t : null;
    let sinceLabel = "desde que abriste el tablero";
    if (firstTs) {
        const ageMs = Date.now() - firstTs;
        const ageH = ageMs / 3_600_000;
        if (ageH < 1) {
            sinceLabel = `desde hace ${Math.max(1, Math.round(ageMs / 60_000))} min`;
        } else if (ageH < 24) {
            sinceLabel = `desde hace ${ageH.toFixed(1)} h`;
        } else {
            sinceLabel = `desde hace ${(ageH / 24).toFixed(1)} días`;
        }
    }
    return (
        <div className="panel p-6 col-span-2" data-testid="equity-hero">
            <div className="flex items-start justify-between">
                <div>
                    <div className="kicker mb-2 flex items-center gap-2">
                        <Wallet size={12} className="text-[var(--green)]" />
                        EQUITY EN VIVO
                    </div>
                    <div className="font-display text-5xl font-black tabular leading-none">
                        {fmtMoney(latest)}
                    </div>
                    <div className="mt-3 flex items-center gap-3 flex-wrap">
                        <div
                            className={`text-sm font-mono tabular ${up ? "text-[var(--green-bright)]" : "text-[var(--red)]"}`}
                        >
                            {up ? "▲" : "▼"} {fmtMoney(Math.abs(change))} ({fmtPct(changePct)})
                        </div>
                        <span className="text-[var(--text-faint)] text-xs font-mono">
                            {sinceLabel} · saldo cerrado: {fmtMoney(balance)}
                        </span>
                    </div>
                </div>
                <div className="text-right">
                    <div className="kicker mb-2">P&L HOY</div>
                    <div className={`font-display text-3xl font-bold tabular ${
                        todayPct >= 0 ? "text-[var(--green-bright)]" : "text-[var(--red)]"
                    }`}>
                        {fmtPct(todayPct)}
                    </div>
                    <div className="kicker mt-1 text-[var(--text-faint)]">
                        cap diario: -{dailyCapPct ?? 3}%
                    </div>
                </div>
            </div>
            <div className="mt-4 h-24" data-testid="equity-sparkline">
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data}
                                margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
                        <YAxis hide domain={["auto", "auto"]} />
                        <ReferenceLine y={baseline}
                                        stroke="rgba(255,255,255,0.2)"
                                        strokeDasharray="3 3" />
                        <Tooltip
                            wrapperStyle={{
                                outline: "none",
                                fontSize: 11,
                                fontFamily: "monospace",
                            }}
                            contentStyle={{
                                background: "rgba(0,0,0,0.85)",
                                border: "1px solid rgba(255,255,255,0.15)",
                                fontSize: 11,
                                fontFamily: "monospace",
                            }}
                            formatter={(v) => [fmtMoney(v), "equity"]}
                            labelFormatter={() => ""}
                        />
                        <Line
                            type="monotone"
                            dataKey="equity"
                            stroke={up ? "#22c55e" : "#ef4444"}
                            strokeWidth={2}
                            dot={false}
                            isAnimationActive={false}
                        />
                    </LineChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}

// --------------------------------------------------------------------------
// PositionVisual — price scale showing SL ─ entry ─ current ─ TP
// --------------------------------------------------------------------------
function PositionVisual({ position, novato = false }) {
    if (!position) {
        return (
            <div className="panel p-5" data-testid="position-empty">
                <div className="kicker mb-3 flex items-center gap-2">
                    <Activity size={12} className="text-[var(--text-faint)]" />
                    POSICIÓN ACTIVA
                </div>
                <div className="text-[var(--text-dim)] text-sm font-mono py-6 text-center">
                    Sin posición abierta — el bot está escaneando
                </div>
            </div>
        );
    }
    const { symbol, side, lots, entry, current, sl, tp, profit_usd, ticket } = position;
    // Compute R progress
    const slDist = Math.abs(entry - sl);
    const rProgress = slDist > 0
        ? (side === "buy" ? (current - entry) / slDist : (entry - current) / slDist)
        : 0;

    // Build the price scale: SL on one end, TP on the other
    const lo = Math.min(sl, tp, entry, current);
    const hi = Math.max(sl, tp, entry, current);
    const range = hi - lo;
    const pct = (p) => range > 0 ? ((p - lo) / range) * 100 : 50;

    const positivePnL = profit_usd >= 0;
    return (
        <div className="panel p-5" data-testid="position-visual">
            <div className="flex items-center justify-between mb-4">
                <div className="kicker flex items-center gap-2">
                    <Activity size={12} className="text-[var(--amber)]" />
                    POSICIÓN ACTIVA
                </div>
                <div className="text-[10px] font-mono text-[var(--text-faint)]">
                    ticket {ticket}
                </div>
            </div>

            <div className="flex items-baseline gap-3 mb-1">
                <div className="font-display text-2xl font-black tabular">{symbol}</div>
                <div className={`text-xs font-mono px-2 py-0.5 border ${
                    side === "buy"
                        ? "border-[var(--green)] text-[var(--green-bright)]"
                        : "border-[var(--red)] text-[var(--red)]"
                }`}>
                    {side === "buy" ? "COMPRA" : "VENTA"} · {novato
                        ? (lots <= 0.05 ? "tamaño chico" : lots <= 0.5 ? "tamaño medio" : "tamaño grande")
                        : `${lots} lots`}
                </div>
            </div>

            <div className={`font-display text-3xl font-black tabular mb-4 ${
                positivePnL ? "text-[var(--green-bright)]" : "text-[var(--red)]"
            }`}>
                {positivePnL ? "+" : ""}{fmtMoney(profit_usd)}
                {!novato && (
                    <span className="text-sm font-mono ml-2 text-[var(--text-faint)]">
                        {rProgress >= 0 ? "+" : ""}{rProgress.toFixed(2)}R
                    </span>
                )}
            </div>

            {/* Price scale */}
            <div className="relative h-2 bg-[var(--bg)] border border-[var(--border)] rounded-sm">
                {/* SL marker */}
                <div className="absolute -top-5 -translate-x-1/2 text-[10px] font-mono text-[var(--red)]"
                     style={{ left: `${pct(sl)}%` }}>
                    SL {sl}
                </div>
                <div className="absolute top-0 bottom-0 w-0.5 bg-[var(--red)]"
                     style={{ left: `${pct(sl)}%` }} />
                {/* Entry marker */}
                <div className="absolute -bottom-5 -translate-x-1/2 text-[10px] font-mono text-white"
                     style={{ left: `${pct(entry)}%` }}>
                    {entry}
                </div>
                <div className="absolute top-0 bottom-0 w-0.5 bg-white"
                     style={{ left: `${pct(entry)}%` }} />
                {/* Current price marker */}
                <div className="absolute top-0 bottom-0 w-1 bg-[var(--amber)]"
                     style={{ left: `${pct(current)}%` }}>
                    <div className="absolute -top-1 -bottom-1 -left-0.5 w-2 bg-[var(--amber)] rounded-full pulse-dot" />
                </div>
                {/* TP marker */}
                <div className="absolute -top-5 -translate-x-1/2 text-[10px] font-mono text-[var(--green-bright)]"
                     style={{ left: `${pct(tp)}%` }}>
                    TP {tp}
                </div>
                <div className="absolute top-0 bottom-0 w-0.5 bg-[var(--green-bright)]"
                     style={{ left: `${pct(tp)}%` }} />
            </div>

            <div className={`mt-7 grid ${novato ? "grid-cols-2" : "grid-cols-3"} gap-3 text-[11px] font-mono`}>
                <div>
                    <div className="kicker text-[var(--text-faint)]">precio</div>
                    <div className="tabular text-white">{current}</div>
                </div>
                {!novato && (
                    <div>
                        <div className="kicker text-[var(--text-faint)]">R progress</div>
                        <div className={`tabular ${rProgress >= 1 ? "text-[var(--green-bright)]" : "text-[var(--text)]"}`}>
                            {rProgress >= 1 ? "🔒 BE locked" : `${rProgress.toFixed(2)}R / 1.00R`}
                        </div>
                    </div>
                )}
                <div>
                    <div className="kicker text-[var(--text-faint)]">a TP</div>
                    <div className="tabular text-[var(--green)]">
                        {Math.abs(tp - current).toFixed(5)}
                    </div>
                </div>
            </div>
        </div>
    );
}

// --------------------------------------------------------------------------
// BotHeartbeat — status of auto_trader + sync_loop + last scan summary
// --------------------------------------------------------------------------
function BotHeartbeat({ procs, lastScan, lastIterTs }) {
    const auto = procs?.auto_trader;
    const sync = procs?.sync_loop;
    const allUp = auto?.alive && sync?.alive;
    const partial = (auto?.alive || sync?.alive) && !allUp;

    return (
        <div className="panel p-5" data-testid="bot-heartbeat">
            <div className="flex items-center justify-between mb-3">
                <div className="kicker flex items-center gap-2">
                    <Cpu size={12} className="text-[var(--green)]" />
                    BOT HEARTBEAT
                </div>
                <div className={`text-[10px] font-mono px-2 py-0.5 border ${
                    allUp ? "border-[var(--green)] text-[var(--green-bright)]"
                    : partial ? "border-[var(--amber)] text-[var(--amber)]"
                    : "border-[var(--red)] text-[var(--red)]"
                }`}>
                    {allUp
                        ? <><Radio size={10} className="inline pulse-dot mr-1" />ACTIVO</>
                        : partial
                            ? "PARCIAL"
                            : <><Pause size={10} className="inline mr-1" />PARADO</>}
                </div>
            </div>

            <div className="grid grid-cols-2 gap-3 mb-4 text-xs">
                <div className={`p-2 border ${auto?.alive ? "border-[var(--green)]" : "border-[var(--red)]"}`}>
                    <div className="font-mono font-semibold">auto_trader</div>
                    <div className="kicker text-[var(--text-faint)]">
                        {auto?.alive ? `PID ${auto.pid}` : "detenido"}
                    </div>
                </div>
                <div className={`p-2 border ${sync?.alive ? "border-[var(--green)]" : "border-[var(--red)]"}`}>
                    <div className="font-mono font-semibold">sync_loop</div>
                    <div className="kicker text-[var(--text-faint)]">
                        {sync?.alive ? `PID ${sync.pid}` : "detenido"}
                    </div>
                </div>
            </div>

            <div className="border-t border-[var(--border)] pt-3">
                <div className="kicker text-[var(--text-faint)] mb-2">
                    último ciclo · hace {timeAgo(lastIterTs)}
                </div>
                {lastScan?.best ? (
                    <div className="text-xs font-mono">
                        mejor: <span className="text-white">{lastScan.best.symbol}</span>
                        {" "}<span className={lastScan.best.side === "buy" ? "text-[var(--green)]" : "text-[var(--red)]"}>
                            {lastScan.best.side === "buy" ? "compra" : "venta"}
                        </span>
                        {" "}score <span className={
                            lastScan.best.score >= 70 ? "text-[var(--green-bright)] font-bold"
                            : lastScan.best.score >= 50 ? "text-[var(--amber)]"
                            : "text-[var(--text-dim)]"
                        }>
                            {lastScan.best.score}
                        </span>
                        {" · "}
                        <span className="text-[var(--text-faint)]">
                            {lastScan.best.rec === "TAKE" ? "TOMAR"
                            : lastScan.best.rec === "WAIT" ? "ESPERAR"
                            : "SALTAR"}
                        </span>
                    </div>
                ) : (
                    <div className="text-xs font-mono text-[var(--text-faint)]">
                        sin datos de escaneo aún
                    </div>
                )}
            </div>
        </div>
    );
}

// --------------------------------------------------------------------------
// DisciplineCard — adherence over last 30 trades
// --------------------------------------------------------------------------
function DisciplineCard({ discipline }) {
    if (!discipline) {
        return (
            <div className="panel p-5">
                <div className="kicker">DISCIPLINA</div>
                <div className="text-xs font-mono text-[var(--text-faint)] mt-2">cargando…</div>
            </div>
        );
    }
    const { adherence_pct, eligible_for_live, verdict, checked, window: w,
            live_threshold_pct, per_rule_counts = {} } = discipline;

    const pct = adherence_pct ?? 0;
    const color = eligible_for_live ? "text-[var(--green-bright)]"
        : pct >= 80 ? "text-[var(--amber)]"
        : "text-[var(--red)]";
    const ringColor = eligible_for_live ? "#22c55e" : pct >= 80 ? "#f59e0b" : "#ef4444";

    return (
        <div className="panel p-5" data-testid="discipline-card">
            <div className="flex items-center justify-between mb-3">
                <div className="kicker flex items-center gap-2">
                    {eligible_for_live ? (
                        <ShieldCheck size={12} className="text-[var(--green)]" />
                    ) : (
                        <AlertTriangle size={12} className="text-[var(--amber)]" />
                    )}
                    DISCIPLINA
                </div>
                <div className="text-[10px] font-mono text-[var(--text-faint)]">
                    {checked} / {w} trades
                </div>
            </div>
            <div className="flex items-center gap-4">
                {/* Circular gauge */}
                <svg width="80" height="80" viewBox="0 0 100 100">
                    <circle cx="50" cy="50" r="45"
                            fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="8" />
                    <circle cx="50" cy="50" r="45"
                            fill="none" stroke={ringColor} strokeWidth="8"
                            strokeDasharray={`${(pct / 100) * 282.7} 282.7`}
                            strokeDashoffset="0"
                            transform="rotate(-90 50 50)"
                            strokeLinecap="round" />
                    <text x="50" y="56" textAnchor="middle"
                          fill="white" fontSize="22" fontFamily="monospace" fontWeight="bold">
                        {pct.toFixed(0)}
                    </text>
                </svg>
                <div className="flex-1">
                    <div className={`font-display text-lg font-bold ${color}`}>
                        {verdict === "ELIGIBLE_FOR_LIVE" ? "Apto para LIVE"
                        : verdict === "GOOD_BUT_NOT_LIVE" ? "Bueno · sigue en demo"
                        : verdict === "POOR" ? "Bajo · revisar bot"
                        : "Datos insuficientes"}
                    </div>
                    <div className="kicker text-[var(--text-faint)] mt-1">
                        umbral live: {live_threshold_pct}% · w={w}
                    </div>
                </div>
            </div>

            {/* Per-rule breakdown */}
            <div className="mt-4 grid grid-cols-2 gap-1.5 text-[10px] font-mono">
                {Object.entries({
                    SL_RUNAWAY: "SL fugado",
                    NO_SL: "Sin SL",
                    WEAK_RR: "R/R débil",
                    REVENGE: "Revancha",
                    OVERTRADING_DAY: "Overtrading",
                }).map(([key, label]) => {
                    const v = per_rule_counts[key] || 0;
                    return (
                        <div key={key}
                             className={`flex justify-between px-2 py-0.5 border ${
                                 v > 0 ? "border-[var(--red)] text-[var(--red)]" : "border-[var(--border)] text-[var(--text-faint)]"
                             }`}>
                            <span>{label}</span>
                            <span className="tabular">{v}</span>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

// --------------------------------------------------------------------------
// Main
// --------------------------------------------------------------------------
export default function LiveDashboard({ api, novato = false, dailyCapPct }) {
    const [mt5, setMt5] = useState(null);
    const [procs, setProcs] = useState({});
    const [lastScan, setLastScan] = useState(null);
    const [lastIterTs, setLastIterTs] = useState(null);
    const [discipline, setDiscipline] = useState(null);
    const [capital, setCapital] = useState(null);
    // El chart de equity se siembra desde el backend al montar (samples
    // persistidas en disco por equity_sampler). Después se appendean ticks
    // nuevos en memoria. Esto resuelve el problema "el chart se reinicia
    // cada vez que entro" — ahora la serie sobrevive refresh / cierre / multi-tab.
    const [samples, setSamples] = useState([]);
    const [samplesLoaded, setSamplesLoaded] = useState(false);

    // Fetch inicial de samples persistidas (last 24h por default).
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const r = await axios.get(`${api}/equity/samples?hours=24&max_n=500`);
                if (cancelled) return;
                if (r.data?.ok && Array.isArray(r.data.samples)) {
                    // Convertir formato backend {ts, equity, balance} →
                    // formato chart {t, equity}
                    const seeded = r.data.samples.map((s) => ({
                        t: new Date(s.ts).getTime(),
                        equity: typeof s.equity === "number" ? s.equity : s.balance,
                    }));
                    setSamples(seeded);
                }
            } catch {
                // silent — chart caerá al modo "in-memory only"
            } finally {
                if (!cancelled) setSamplesLoaded(true);
            }
        })();
        return () => { cancelled = true; };
    }, [api]);

    const refresh = useCallback(async () => {
        try {
            const [m, pl, bs, dc, cap] = await Promise.allSettled([
                axios.get(`${api}/mt5/status`),
                axios.get(`${api}/process/list`),
                axios.get(`${api}/bot/status`),
                axios.get(`${api}/discipline/score?window=30`),
                apiGet("/capital"),
            ]);
            if (m.status === "fulfilled") {
                setMt5(m.value.data);
                const eq = m.value.data?.account?.equity;
                if (typeof eq === "number" && Number.isFinite(eq)) {
                    setSamples((prev) => {
                        const next = [...prev, { t: Date.now(), equity: eq }];
                        if (next.length > MAX_SAMPLES) {
                            return next.slice(next.length - MAX_SAMPLES);
                        }
                        return next;
                    });
                }
            }
            if (pl.status === "fulfilled") {
                const map = {};
                (pl.value.data?.processes || []).forEach((p) => { map[p.name] = p; });
                setProcs(map);
            }
            if (bs.status === "fulfilled") {
                setLastScan(bs.value.data?.last_scan || null);
                setLastIterTs(bs.value.data?.last_iter_ts || null);
            }
            if (dc.status === "fulfilled") {
                setDiscipline(dc.value.data);
            }
            if (cap.status === "fulfilled") {
                setCapital(cap.value.data);
            }
        } catch {
            // silent — show stale data
        }
    }, [api]);

    useEffect(() => {
        refresh();
        const id = setInterval(refresh, TICK_MS);
        return () => clearInterval(id);
    }, [refresh]);

    const acc = mt5?.account || {};
    const today = mt5?.today || {};
    // Antes hardcodeaba 200 como starting balance hint. Ahora preferimos el
    // valor real desde /api/capital si está disponible.
    const balance = acc.balance ?? capital?.starting_balance_usd ?? capital?.current_capital_usd ?? 0;
    const equity = acc.equity ?? balance;
    const positions = mt5?.open_positions || [];
    const activePos = positions[0] || null;

    return (
        <section
            id="live"
            className="px-6 lg:px-10 py-8 border-b border-[var(--border)]"
            data-testid="section-live"
        >
            <div className="max-w-[1400px] mx-auto">
                <div className="flex items-end justify-between mb-6 gap-4 flex-wrap">
                    <div>
                        <div className="kicker mb-1">SECCIÓN 00 / EN VIVO</div>
                        <h2 className="font-display text-3xl md:text-4xl font-black tracking-tight">
                            Tablero en Vivo
                        </h2>
                        <p className="mt-2 text-[var(--text-dim)] max-w-[640px] text-sm">
                            Refresca cada 3 s. Si algo se mueve en MT5 o en el bot, aparece aquí
                            sin que tengas que recargar.
                        </p>
                    </div>
                </div>

                {/* TOP ROW: equity hero (2 cols) + position visual (1 col) */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
                    <EquityHero
                        samples={samples}
                        balance={balance}
                        equity={equity}
                        todayPct={today.total_pl_pct ?? 0}
                        dailyCapPct={dailyCapPct}
                    />
                    <PositionVisual position={activePos} novato={novato} />
                </div>

                {/* SECOND ROW: bot heartbeat + (en experto) discipline */}
                <div className={`grid grid-cols-1 ${novato ? "" : "md:grid-cols-2"} gap-4`}>
                    <BotHeartbeat
                        procs={procs}
                        lastScan={lastScan}
                        lastIterTs={lastIterTs}
                    />
                    {!novato && <DisciplineCard discipline={discipline} />}
                </div>
            </div>
        </section>
    );
}
