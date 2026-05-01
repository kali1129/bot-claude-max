import { useEffect, useState, useCallback, useRef } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Cpu, Play, Square, RotateCw, Terminal, Radio, Target, Pause,  } from "lucide-react";

const TOKEN = process.env.REACT_APP_DASHBOARD_TOKEN || "";
const authHeaders = TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};

const PROC_NAMES = {
    auto_trader: { label: "Bot autónomo", desc: "Escanea → decide → opera" },
    sync_loop:   { label: "Sincronizador", desc: "MT5 → diario, cada 30s" },
};

const SCORE_COLOR = (s) =>
    s >= 70 ? "text-[var(--green-bright)]"
    : s >= 50 ? "text-[var(--amber)]"
    : "text-[var(--text-dim)]";

const REC_COLOR = (r) =>
    r === "TAKE" ? "text-[var(--green-bright)]"
    : r === "WAIT" ? "text-[var(--amber)]"
    : "text-[var(--text-dim)]";

const REC_ES = (r) => r === "TAKE" ? "TOMAR" : r === "WAIT" ? "ESPERAR" : "SALTAR";

function fmtTimeAgo(iso) {
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
}

function ProcessCard({ name, info, onStart, onStop, onRestart, busy }) {
    const meta = PROC_NAMES[name] || { label: name, desc: "" };
    const alive = info?.alive;
    return (
        <div
            className={`panel p-4 ${alive ? "border-[var(--green)]" : "border-[var(--red)]"}`}
            data-testid={`proc-card-${name}`}
        >
            <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                    <div
                        className={`w-2 h-2 rounded-full ${
                            alive ? "bg-[var(--green)] pulse-dot" : "bg-[var(--red)]"
                        }`}
                    />
                    <div>
                        <div className="font-mono text-sm font-semibold">{meta.label}</div>
                        <div className="kicker text-[var(--text-faint)]">{meta.desc}</div>
                    </div>
                </div>
                <div
                    className={`text-[10px] font-mono px-2 py-0.5 border ${
                        alive
                            ? "border-[var(--green)] text-[var(--green-bright)]"
                            : "border-[var(--red)] text-[var(--red)]"
                    }`}
                >
                    {alive ? "ACTIVO" : "DETENIDO"}
                </div>
            </div>
            {alive && info?.pid && (
                <div className="kicker text-[var(--text-faint)] mb-3">
                    PID {info.pid}
                </div>
            )}
            <div className="flex gap-2">
                {alive ? (
                    <>
                        <button
                            onClick={() => onStop(name)}
                            disabled={busy}
                            className="btn-sharp danger flex items-center gap-1 text-xs"
                            data-testid={`proc-stop-${name}`}
                        >
                            <Square size={12} /> Detener
                        </button>
                        <button
                            onClick={() => onRestart(name)}
                            disabled={busy}
                            className="btn-sharp flex items-center gap-1 text-xs"
                            data-testid={`proc-restart-${name}`}
                        >
                            <RotateCw size={12} /> Reiniciar
                        </button>
                    </>
                ) : (
                    <button
                        onClick={() => onStart(name)}
                        disabled={busy}
                        className="btn-sharp primary flex items-center gap-1 text-xs"
                        data-testid={`proc-start-${name}`}
                    >
                        <Play size={12} /> Arrancar
                    </button>
                )}
            </div>
        </div>
    );
}

function LastScanCard({ scan }) {
    if (!scan) {
        return (
            <div className="panel p-4">
                <div className="flex items-center gap-2 mb-2">
                    <Target size={14} className="text-[var(--blue)]" />
                    <div className="kicker">Último escaneo</div>
                </div>
                <div className="text-[var(--text-dim)] text-xs font-mono">
                    Sin escaneos aún. El bot arranca el escaneo en su primer ciclo (cada 30 s).
                </div>
            </div>
        );
    }
    const { ts, best, candidates = [] } = scan;
    return (
        <div className="panel p-4">
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <Target size={14} className="text-[var(--blue)]" />
                    <div className="kicker">Último escaneo · hace {fmtTimeAgo(ts)}</div>
                </div>
                {best && (
                    <div
                        className={`text-[10px] font-mono px-2 py-0.5 border ${
                            best.rec === "TAKE"
                                ? "border-[var(--green)] text-[var(--green-bright)]"
                                : "border-[var(--amber)] text-[var(--amber)]"
                        }`}
                    >
                        Mejor: {best.symbol} · {best.score}
                    </div>
                )}
            </div>
            <div className="overflow-x-auto">
                <table className="w-full text-[11px] font-mono tabular">
                    <thead>
                        <tr className="text-[var(--text-faint)] border-b border-[var(--border)]">
                            <th className="text-left py-1.5">Símbolo</th>
                            <th className="text-left py-1.5">Lado</th>
                            <th className="text-right py-1.5">Score</th>
                            <th className="text-right py-1.5">Decisión</th>
                            <th className="text-right py-1.5">Entry</th>
                        </tr>
                    </thead>
                    <tbody>
                        {candidates.slice(0, 14).map((c, i) => {
                            if (c.status || c.error) {
                                return (
                                    <tr key={i} className="border-b border-[var(--border)]">
                                        <td className="py-1">{c.symbol}</td>
                                        <td colSpan={4} className="py-1 text-[var(--text-faint)]">
                                            {c.status || `error: ${c.error}`}
                                        </td>
                                    </tr>
                                );
                            }
                            return (
                                <tr key={i} className="border-b border-[var(--border)]">
                                    <td className="py-1">{c.symbol}</td>
                                    <td className="py-1">
                                        <span
                                            className={
                                                c.side === "buy"
                                                    ? "text-[var(--green)]"
                                                    : "text-[var(--red)]"
                                            }
                                        >
                                            {c.side === "buy" ? "C" : "V"}
                                        </span>
                                    </td>
                                    <td className={`py-1 text-right font-bold ${SCORE_COLOR(c.score)}`}>
                                        {c.score}
                                    </td>
                                    <td className={`py-1 text-right ${REC_COLOR(c.rec)}`}>
                                        {REC_ES(c.rec)}
                                    </td>
                                    <td className="py-1 text-right">{c.entry}</td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

function LogTail({ lines, label = "Log del bot" }) {
    const ref = useRef(null);
    useEffect(() => {
        if (ref.current) {
            ref.current.scrollTop = ref.current.scrollHeight;
        }
    }, [lines]);
    return (
        <div className="panel p-4 h-full">
            <div className="flex items-center gap-2 mb-3">
                <Terminal size={14} className="text-[var(--green)]" />
                <div className="kicker">{label}</div>
            </div>
            <div
                ref={ref}
                className="bg-[var(--bg)] border border-[var(--border)] p-3 h-64 overflow-y-auto font-mono text-[10.5px] leading-snug"
                data-testid="bot-log-tail"
            >
                {(!lines || lines.length === 0) ? (
                    <div className="text-[var(--text-faint)]">Sin actividad aún.</div>
                ) : (
                    lines.map((line, i) => {
                        const isError = /error|fail|reject|HALT/i.test(line);
                        const isOpen = /place_order.*ok.*True|opened|setup/i.test(line);
                        const isClose = /closed|TP|SL hit/i.test(line);
                        return (
                            <div
                                key={i}
                                className={
                                    isError
                                        ? "text-[var(--red)]"
                                        : isOpen
                                            ? "text-[var(--green-bright)]"
                                            : isClose
                                                ? "text-[var(--amber)]"
                                                : "text-[var(--text-dim)]"
                                }
                            >
                                {line}
                            </div>
                        );
                    })
                )}
            </div>
        </div>
    );
}

export default function BotLiveStatus({ api }) {
    const [procs, setProcs] = useState({});
    const [logs, setLogs] = useState([]);
    const [scan, setScan] = useState(null);
    const [busy, setBusy] = useState(false);

    const refresh = useCallback(async () => {
        try {
            const [pl, lg, st] = await Promise.all([
                axios.get(`${api}/process/list`),
                axios.get(`${api}/process/auto_trader/log?lines=40`),
                axios.get(`${api}/bot/status`),
            ]);
            const map = {};
            (pl.data?.processes || []).forEach((p) => { map[p.name] = p; });
            setProcs(map);
            setLogs(lg.data?.lines || []);
            setScan(st.data?.last_scan || null);
        } catch (e) {
            // silent — show stale data
        }
    }, [api]);

    useEffect(() => {
        refresh();
        const id = setInterval(refresh, 3000);   // 3s aggressive polling — this section is "live"
        return () => clearInterval(id);
    }, [refresh]);

    const onAction = async (action, name) => {
        try {
            setBusy(true);
            const url = `${api}/process/${name}/${action}`;
            const r = await axios.post(url, {}, { headers: authHeaders });
            if (r.data?.ok) {
                toast.success(`${PROC_NAMES[name]?.label || name}: ${action}`);
            } else {
                toast.error(`${name}/${action}: ${r.data?.reason || "fallo"}`);
            }
            await refresh();
        } catch (e) {
            toast.error(`${name}/${action}: ${e.response?.status || e.message}`);
        } finally {
            setBusy(false);
        }
    };

    const onStart   = (n) => onAction("start", n);
    const onStop    = (n) => onAction("stop", n);
    const onRestart = (n) => onAction("restart", n);

    const auto = procs.auto_trader;
    const sync = procs.sync_loop;
    const allDown = !auto?.alive && !sync?.alive;

    return (
        <div className="panel mb-6 p-5" data-testid="bot-live-status">
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                    <Cpu size={16} className="text-[var(--green)]" />
                    <span className="kicker">Bot en vivo · refresca cada 3 s</span>
                </div>
                <div className="flex items-center gap-2">
                    {allDown ? (
                        <span className="kicker text-[var(--red)]">
                            <Pause size={11} className="inline mr-1" />
                            BOT PARADO
                        </span>
                    ) : (
                        <span className="kicker text-[var(--green-bright)]">
                            <Radio size={11} className="inline mr-1 pulse-dot" />
                            BOT ACTIVO
                        </span>
                    )}
                </div>
            </div>

            {/* Process cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
                <ProcessCard
                    name="auto_trader"
                    info={auto}
                    onStart={onStart}
                    onStop={onStop}
                    onRestart={onRestart}
                    busy={busy}
                />
                <ProcessCard
                    name="sync_loop"
                    info={sync}
                    onStart={onStart}
                    onStop={onStop}
                    onRestart={onRestart}
                    busy={busy}
                />
            </div>

            {/* Last scan + Live log side-by-side */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                <LastScanCard scan={scan} />
                <LogTail lines={logs} label="Log del bot · auto_trader" />
            </div>
        </div>
    );
}
