import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
    Activity,
    Wallet,
    TrendingUp,
    AlertTriangle,
    Power,
    RefreshCw,
    Zap,
    CheckCircle2,
    XCircle,
    Server,
} from "lucide-react";
import BotPanel from "./BotPanel";
import BotLiveStatus from "./BotLiveStatus";

const TOKEN = process.env.REACT_APP_DASHBOARD_TOKEN || "";
const authHeaders = TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};

const fmtMoney = (v, currency = "USD") =>
    typeof v === "number"
        ? `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`
        : "—";

const fmtPct = (v) =>
    typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` : "—";

const StatusDot = ({ ok, label }) => (
    <div className="flex items-center gap-2">
        {ok ? (
            <CheckCircle2 size={16} className="text-[var(--green)]" />
        ) : (
            <XCircle size={16} className="text-[var(--red)]" />
        )}
        <span className="font-mono text-xs text-[var(--text-dim)]">{label}</span>
    </div>
);

export default function ControlPanel({ api, onMutated }) {
    const [health, setHealth] = useState(null);
    const [mt5, setMt5] = useState(null);
    const [loading, setLoading] = useState(false);
    const [syncing, setSyncing] = useState(false);
    const [haltLoading, setHaltLoading] = useState(false);
    const [lastSync, setLastSync] = useState(null);

    const refresh = useCallback(async () => {
        try {
            const [h, m] = await Promise.all([
                axios.get(`${api}/system/health`),
                axios.get(`${api}/mt5/status`),
            ]);
            setHealth(h.data);
            setMt5(m.data);
        } catch (e) {
            console.error("control panel refresh", e);
        }
    }, [api]);

    useEffect(() => {
        setLoading(true);
        refresh().finally(() => setLoading(false));
        const id = setInterval(refresh, 4000);   // bumped from 8s for live feel
        return () => clearInterval(id);
    }, [refresh]);

    const triggerHalt = async () => {
        if (!window.confirm("¿Detener TODO el trading? Las órdenes nuevas se rechazarán hasta que reanudes."))
            return;
        try {
            setHaltLoading(true);
            await axios.post(
                `${api}/halt`,
                { reason: "Botón de pánico (dashboard)" },
                { headers: authHeaders }
            );
            toast.success("Trading detenido. Las órdenes nuevas serán rechazadas.");
            await refresh();
        } catch (e) {
            toast.error(`No se pudo detener: ${e.response?.status || e.message}`);
        } finally {
            setHaltLoading(false);
        }
    };

    const triggerResume = async () => {
        if (!window.confirm("¿Reanudar el trading?"))
            return;
        try {
            setHaltLoading(true);
            await axios.delete(`${api}/halt`, { headers: authHeaders });
            toast.success("Trading reanudado.");
            await refresh();
        } catch (e) {
            toast.error(`No se pudo reanudar: ${e.response?.status || e.message}`);
        } finally {
            setHaltLoading(false);
        }
    };

    const triggerSync = async () => {
        try {
            setSyncing(true);
            const r = await axios.post(
                `${api}/mt5/sync`,
                { lookback_days: 7 },
                { headers: authHeaders }
            );
            const pushed = r.data.pushed?.length || 0;
            const failed = r.data.failed?.length || 0;
            setLastSync({ pushed, failed, at: new Date() });
            if (r.data.ok === false) {
                toast.error(`Error al sincronizar: ${r.data.reason}`);
            } else if (pushed === 0) {
                toast.success("Ya estás al día. No hay operaciones nuevas que sincronizar.");
            } else {
                toast.success(`${pushed} operación(es) nueva(s) añadida(s) a tu diario.`);
            }
            await refresh();
            onMutated?.();
        } catch (e) {
            toast.error(`No se pudo sincronizar: ${e.response?.status || e.message}`);
        } finally {
            setSyncing(false);
        }
    };

    const acc = mt5?.account;
    const today = mt5?.today;
    const positions = mt5?.open_positions || [];
    const halted = health?.trading_halted;

    return (
        <section id="control" className="px-6 lg:px-10 py-12 border-b border-[var(--border)]">
            {/* Header */}
            <div className="mb-8">
                <div className="kicker mb-2">// 01 · PANEL DE CONTROL</div>
                <h2 className="font-display text-3xl font-black tracking-tight">
                    Centro de Mando
                </h2>
                <p className="text-[var(--text-dim)] text-sm mt-2 max-w-2xl">
                    Aquí controlas tu cuenta de trading. Todo lo importante en un solo
                    lugar — sin abrir la consola, sin tocar archivos, sin escribir código.
                </p>
            </div>

            {/* Big status banner */}
            <div
                className={`panel mb-6 px-5 py-4 flex items-center justify-between ${
                    halted ? "stripes-danger" : ""
                }`}
                data-testid="status-banner"
            >
                <div className="flex items-center gap-4">
                    <div
                        className={`w-3 h-3 rounded-full ${
                            halted ? "bg-[var(--red)]" : "bg-[var(--green)] pulse-dot"
                        }`}
                    />
                    <div>
                        <div className="kicker">
                            {halted ? "🛑 TRADING DETENIDO" : "✓ TRADING ACTIVO"}
                        </div>
                        <div className="font-mono text-xs text-[var(--text-dim)] mt-1">
                            {halted
                                ? `Las órdenes nuevas serán rechazadas. Razón: ${health?.halt_reason || "—"}`
                                : "El sistema está operativo. Las reglas de seguridad están vigilando cada orden."}
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    {halted ? (
                        <button
                            data-testid="resume-button"
                            onClick={triggerResume}
                            disabled={haltLoading}
                            className="btn-sharp primary flex items-center gap-2"
                        >
                            <Power size={14} />
                            {haltLoading ? "Reanudando…" : "Reanudar Trading"}
                        </button>
                    ) : (
                        <button
                            data-testid="halt-button"
                            onClick={triggerHalt}
                            disabled={haltLoading}
                            className="btn-sharp danger flex items-center gap-2"
                        >
                            <AlertTriangle size={14} />
                            {haltLoading ? "Deteniendo…" : "Botón de Pánico"}
                        </button>
                    )}
                </div>
            </div>

            {/* 4-column grid */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
                {/* Account */}
                <div className="panel p-5" data-testid="card-account">
                    <div className="flex items-center justify-between mb-4">
                        <div className="flex items-center gap-2">
                            <Wallet size={16} className="text-[var(--green)]" />
                            <span className="kicker">Tu cuenta</span>
                        </div>
                        {acc?.trade_allowed ? (
                            <span className="kicker text-[var(--green)]">
                                Operaciones permitidas
                            </span>
                        ) : (
                            <span className="kicker text-[var(--red)]">Bloqueada</span>
                        )}
                    </div>
                    {acc ? (
                        <>
                            <div className="font-display text-3xl font-black tabular">
                                {fmtMoney(acc.equity, acc.currency)}
                            </div>
                            <div className="kicker mt-1 text-[var(--text-faint)]">
                                Capital actual (incluye ganancias no realizadas)
                            </div>
                            <div className="grid grid-cols-2 gap-4 mt-5 text-xs">
                                <div>
                                    <div className="kicker text-[var(--text-faint)]">Saldo</div>
                                    <div className="font-mono mt-1 tabular">
                                        {fmtMoney(acc.balance, acc.currency)}
                                    </div>
                                </div>
                                <div>
                                    <div className="kicker text-[var(--text-faint)]">Margen libre</div>
                                    <div className="font-mono mt-1 tabular">
                                        {fmtMoney(acc.margin_free, acc.currency)}
                                    </div>
                                </div>
                                <div>
                                    <div className="kicker text-[var(--text-faint)]">Cuenta</div>
                                    <div className="font-mono mt-1">
                                        {acc.login} · {acc.name}
                                    </div>
                                </div>
                                <div>
                                    <div className="kicker text-[var(--text-faint)]">Broker</div>
                                    <div className="font-mono mt-1">{acc.server}</div>
                                </div>
                            </div>
                        </>
                    ) : (
                        <div data-testid="mt5-disconnected">
                            <div className="font-display text-2xl font-black mb-2 text-[var(--amber)]">
                                MT5 sin conectar
                            </div>
                            <div className="text-[var(--text-dim)] text-xs leading-relaxed mb-4">
                                {loading
                                    ? "Buscando MetaTrader…"
                                    : "El dashboard funciona, pero no ve tu cuenta. Para conectarla:"}
                            </div>
                            {!loading && (
                                <ol className="text-xs text-[var(--text-dim)] font-mono space-y-2 list-decimal list-inside">
                                    <li>Abre el terminal MetaTrader 5 (XM Global MT5).</li>
                                    <li>
                                        En MT5: <span className="text-white">Archivo → Conectarse a cuenta de operaciones</span>
                                    </li>
                                    <li>
                                        Usa las credenciales y el servidor configurados en{" "}
                                        <a href="#config" className="text-[var(--green-bright)] underline">Configuración</a>.
                                    </li>
                                    <li>El dashboard se actualiza solo en menos de 5 segundos.</li>
                                </ol>
                            )}
                            {mt5?.reason && (
                                <div className="mt-4 text-[10px] text-[var(--text-faint)] font-mono">
                                    Detalle técnico: {mt5.reason}
                                </div>
                            )}
                        </div>
                    )}
                </div>

                {/* Today P&L */}
                <div className="panel p-5" data-testid="card-today">
                    <div className="flex items-center justify-between mb-4">
                        <div className="flex items-center gap-2">
                            <TrendingUp size={16} className="text-[var(--blue)]" />
                            <span className="kicker">Resultado de hoy</span>
                        </div>
                    </div>
                    {today ? (
                        <>
                            <div
                                className={`font-display text-3xl font-black tabular ${
                                    today.total_pl_usd > 0
                                        ? "text-[var(--green-bright)]"
                                        : today.total_pl_usd < 0
                                            ? "text-[var(--red)]"
                                            : "text-[var(--text)]"
                                }`}
                            >
                                {today.total_pl_usd >= 0 ? "+" : ""}
                                {fmtMoney(today.total_pl_usd, acc?.currency || "USD")}
                            </div>
                            <div className="kicker mt-1 text-[var(--text-faint)]">
                                {fmtPct(today.total_pl_pct)} sobre tu saldo
                            </div>
                            <div className="grid grid-cols-2 gap-4 mt-5 text-xs">
                                <div>
                                    <div className="kicker text-[var(--text-faint)]">Ya cobrado</div>
                                    <div className="font-mono mt-1 tabular">
                                        {fmtMoney(today.realised_pl_usd, acc?.currency || "USD")}
                                    </div>
                                </div>
                                <div>
                                    <div className="kicker text-[var(--text-faint)]">Flotando</div>
                                    <div className="font-mono mt-1 tabular">
                                        {fmtMoney(today.unrealised_pl_usd, acc?.currency || "USD")}
                                    </div>
                                </div>
                            </div>
                            {today.total_pl_pct <= -2.5 && (
                                <div className="mt-4 text-[11px] text-[var(--amber)] font-mono stripes-warn p-2">
                                    ⚠ Estás cerca del límite del día (-3%). Considera detener.
                                </div>
                            )}
                        </>
                    ) : (
                        <div className="text-[var(--text-dim)] text-sm">Sin datos.</div>
                    )}
                </div>
            </div>

            {/* Open positions */}
            <div className="panel p-5 mb-6" data-testid="card-positions">
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                        <Activity size={16} className="text-[var(--amber)]" />
                        <span className="kicker">Posiciones abiertas ({positions.length})</span>
                    </div>
                    <span className="kicker text-[var(--text-faint)]">
                        Regla: máximo 1 posición a la vez
                    </span>
                </div>
                {positions.length === 0 ? (
                    <div className="text-[var(--text-dim)] text-sm font-mono">
                        No tienes ninguna operación abierta. Listo para el próximo setup.
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full text-xs font-mono tabular">
                            <thead>
                                <tr className="text-[var(--text-faint)] border-b border-[var(--border)]">
                                    <th className="text-left py-2">Símbolo</th>
                                    <th className="text-left py-2">Lado</th>
                                    <th className="text-right py-2">Tamaño</th>
                                    <th className="text-right py-2">Entrada</th>
                                    <th className="text-right py-2">Precio actual</th>
                                    <th className="text-right py-2">Stop / Objetivo</th>
                                    <th className="text-right py-2">Ganancia/Pérdida</th>
                                </tr>
                            </thead>
                            <tbody>
                                {positions.map((p) => (
                                    <tr
                                        key={p.ticket}
                                        className="border-b border-[var(--border)]"
                                        data-testid={`position-${p.ticket}`}
                                    >
                                        <td className="py-2.5">{p.symbol}</td>
                                        <td className="py-2.5">
                                            <span
                                                className={
                                                    p.side === "buy"
                                                        ? "text-[var(--green)]"
                                                        : "text-[var(--red)]"
                                                }
                                            >
                                                {p.side === "buy" ? "Compra" : "Venta"}
                                            </span>
                                        </td>
                                        <td className="py-2.5 text-right">{p.lots}</td>
                                        <td className="py-2.5 text-right">{p.entry}</td>
                                        <td className="py-2.5 text-right">{p.current}</td>
                                        <td className="py-2.5 text-right">
                                            <span className="text-[var(--red)]">{p.sl || "—"}</span>
                                            {" / "}
                                            <span className="text-[var(--green)]">{p.tp || "—"}</span>
                                        </td>
                                        <td
                                            className={`py-2.5 text-right ${
                                                p.profit_usd > 0
                                                    ? "text-[var(--green-bright)]"
                                                    : p.profit_usd < 0
                                                        ? "text-[var(--red)]"
                                                        : ""
                                            }`}
                                        >
                                            {p.profit_usd >= 0 ? "+" : ""}
                                            {fmtMoney(p.profit_usd)}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                        {positions.some((p) => !p.sl) && (
                            <div className="mt-3 text-[11px] text-[var(--red)] font-mono stripes-danger p-2">
                                ⚠ Tienes una posición SIN stop loss. Edítala en MT5 cuanto antes — la regla del sistema requiere SL siempre.
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Actions row */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
                <div className="panel p-5">
                    <div className="flex items-center gap-2 mb-3">
                        <RefreshCw size={16} className="text-[var(--blue)]" />
                        <span className="kicker">Sincronizar diario</span>
                    </div>
                    <p className="text-xs text-[var(--text-dim)] mb-4">
                        Trae a tu diario las operaciones cerradas en MetaTrader de los
                        últimos 7 días. Es seguro hacerlo varias veces — no se duplican.
                    </p>
                    <button
                        data-testid="sync-button"
                        onClick={triggerSync}
                        disabled={syncing}
                        className="btn-sharp primary flex items-center gap-2"
                    >
                        <RefreshCw size={14} className={syncing ? "animate-spin" : ""} />
                        {syncing ? "Sincronizando…" : "Sincronizar ahora"}
                    </button>
                    {lastSync && (
                        <div className="mt-3 text-[11px] text-[var(--text-faint)] font-mono">
                            Última: {lastSync.pushed} nueva(s), {lastSync.failed} fallida(s)
                            {" — "}
                            {lastSync.at.toLocaleTimeString("es-ES")}
                        </div>
                    )}
                </div>

                <div className="panel p-5">
                    <div className="flex items-center gap-2 mb-3">
                        <Zap size={16} className="text-[var(--amber)]" />
                        <span className="kicker">Estado del sistema</span>
                    </div>
                    <p className="text-xs text-[var(--text-dim)] mb-4">
                        Si alguno está en rojo, hay algo desconectado. Los detalles
                        están en el panel del terminal.
                    </p>
                    <div className="grid grid-cols-2 gap-y-3 text-xs">
                        <StatusDot
                            ok={health?.backend}
                            label="Servidor del dashboard"
                        />
                        <StatusDot
                            ok={health?.database}
                            label="Base de datos (diario)"
                        />
                        <StatusDot
                            ok={health?.mt5}
                            label="MetaTrader 5"
                        />
                        <StatusDot
                            ok={!health?.trading_halted}
                            label="Trading habilitado"
                        />
                    </div>
                    {health?.mt5_account && (
                        <div className="mt-4 text-[11px] text-[var(--text-faint)] font-mono">
                            Conectado a la cuenta {health.mt5_account}
                        </div>
                    )}
                </div>
            </div>

            {/* Bot live status — process control + last scan + live log */}
            <BotLiveStatus api={api} />

            {/* Bot panel — scan, manual trade, log, config */}
            <BotPanel api={api} onMutated={onMutated} />

            {/* API endpoints reference (so external clients / Claude can drive the bot) */}
            <div className="panel p-4 text-[11px] font-mono text-[var(--text-dim)] mt-4">
                <div className="flex items-start gap-3">
                    <Server size={14} className="text-[var(--text-faint)] mt-0.5 flex-shrink-0" />
                    <div className="flex-1">
                        <div className="kicker mb-2">Endpoints REST disponibles</div>
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-6 gap-y-1">
                            <div><span className="text-[var(--green)]">GET</span> /api/system/health — estado general</div>
                            <div><span className="text-[var(--green)]">GET</span> /api/mt5/status — cuenta + posiciones</div>
                            <div><span className="text-[var(--green)]">GET</span> /api/bot/status — bot vivo + último escaneo</div>
                            <div><span className="text-[var(--green)]">GET</span> /api/bot/log?n=N — actividad reciente</div>
                            <div><span className="text-[var(--green)]">GET</span> /api/bot/config — configuración</div>
                            <div><span className="text-[var(--green)]">GET</span> /api/journal — historial de operaciones</div>
                            <div><span className="text-[var(--green)]">GET</span> /api/discipline/score — % adherencia (gate live)</div>
                            <div><span className="text-[var(--green)]">GET</span> /api/process/list — auto_trader + sync_loop</div>
                            <div><span className="text-[var(--amber)]">POST</span> /api/bot/scan — escaneo inmediato</div>
                            <div><span className="text-[var(--amber)]">POST</span> /api/bot/execute — operar manualmente</div>
                            <div><span className="text-[var(--amber)]">POST</span> /api/halt — botón de pánico</div>
                            <div><span className="text-[var(--amber)]">POST</span> /api/mt5/sync — sincronizar deals MT5</div>
                            <div><span className="text-[var(--amber)]">POST</span> /api/process/&#123;name&#125;/start — arrancar proceso</div>
                            <div><span className="text-[var(--amber)]">POST</span> /api/process/&#123;name&#125;/stop — detener proceso</div>
                            <div><span className="text-[var(--red)]">DELETE</span> /api/halt — reanudar trading</div>
                        </div>
                        <div className="mt-3 text-[var(--text-faint)]">
                            Estos endpoints permiten que cualquier cliente HTTP
                            (incluido Claude) lea lo que el bot ve y opere por
                            ti — todas las reglas de seguridad se aplican igual.
                        </div>
                    </div>
                </div>
            </div>
        </section>
    );
}
