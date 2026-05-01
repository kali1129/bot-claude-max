// MyAccount — página personal del usuario logueado.
//
// Contiene:
//   - Card "Tu cuenta" con email + display_name + role + paid_until
//   - Card "Conectar broker" — form MT5 (login/password/server/path/demo)
//   - Card "Bot" — start/stop + trial 24h timer + slot info
//   - Card "Slot info" — cuántos bots activos hay globalmente
//
// FASE 2: la conexión MT5 se valida con un test placeholder. La conexión
// REAL al broker (que opere por el usuario) llega en FASE 3 cuando esté
// el supervisor con Wine prefix per user.

import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import {
    User, KeyRound, Server, Eye, EyeOff, Save, Trash2, PlayCircle,
    PauseCircle, Clock, Shield, AlertTriangle, ExternalLink, Loader2,
    CheckCircle2, XCircle, RefreshCcw, Terminal, FileText,
} from "lucide-react";

import { apiGet, apiPost, apiDelete } from "@/lib/api";
import { useAuth } from "@/lib/AuthProvider";

import SectionHeader from "@/components/atoms/SectionHeader";
import KpiCard from "@/components/atoms/KpiCard";
import SkeletonPanel from "@/components/atoms/SkeletonPanel";
import WarningModal from "@/components/atoms/WarningModal";
import ReferralBanner from "@/components/atoms/ReferralBanner";

const XM_SERVERS = [
    "XMGlobal-MT5",
    "XMGlobal-MT5 2",
    "XMGlobal-MT5 3",
    "XMGlobal-MT5 4",
    "XMGlobal-MT5 5",
    "XMGlobal-MT5 6",
    "XMGlobal-Real",
    "XMGlobal-Demo",
];

function formatRemaining(seconds) {
    if (seconds == null || seconds < 0) return "—";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
    if (h >= 1) return `${h}h ${m}m`;
    return `${m}m`;
}

export default function MyAccount() {
    const { user, isAdmin } = useAuth();
    const [broker, setBroker] = useState(null);
    const [bot, setBot] = useState(null);
    const [slots, setSlots] = useState(null);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);

    // Form state
    const [form, setForm] = useState({
        mt5_login: "",
        mt5_password: "",
        mt5_server: "XMGlobal-MT5 6",
        mt5_path: "",
        is_demo: true,
    });
    const [showPwd, setShowPwd] = useState(false);
    const [testResult, setTestResult] = useState(null);
    const [confirmDelete, setConfirmDelete] = useState(false);

    const [logs, setLogs] = useState("");
    const [logsWhich, setLogsWhich] = useState("stdout");
    const [showLogs, setShowLogs] = useState(false);

    const refresh = useCallback(async () => {
        try {
            const [b, bt, s] = await Promise.allSettled([
                apiGet("/users/me/broker"),
                apiGet("/users/me/bot"),
                apiGet("/users/me/bot/slots"),
            ]);
            if (b.status === "fulfilled") {
                if (b.value.data?.has_creds) setBroker(b.value.data);
                else setBroker(null);
            }
            if (bt.status === "fulfilled") setBot(bt.value.data);
            if (s.status === "fulfilled") setSlots(s.value.data);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }, []);

    const fetchLogs = useCallback(async () => {
        try {
            const r = await apiGet(`/users/me/bot/logs?lines=200&which=${logsWhich}`);
            setLogs(r.data?.logs || "(sin logs todavía)");
        } catch (e) {
            setLogs("[error: " + (e.response?.data?.detail || e.message) + "]");
        }
    }, [logsWhich]);

    useEffect(() => {
        if (showLogs) {
            fetchLogs();
            const id = setInterval(fetchLogs, 5000);
            return () => clearInterval(id);
        }
    }, [showLogs, fetchLogs]);

    useEffect(() => {
        refresh();
        const id = setInterval(refresh, 8000);
        return () => clearInterval(id);
    }, [refresh]);

    const updateField = (k, v) => {
        setForm((p) => ({ ...p, [k]: v }));
        setTestResult(null);
    };

    const test = async () => {
        if (!form.mt5_login || !form.mt5_password || !form.mt5_server) {
            toast.error("Login, password y servidor son obligatorios");
            return;
        }
        setBusy(true);
        try {
            const r = await apiPost("/users/me/broker/test", {
                ...form,
                mt5_login: parseInt(form.mt5_login, 10),
            });
            setTestResult(r.data);
            if (r.data?.ok) toast.success("Datos válidos. Podés guardar.");
            else toast.error(r.data?.error || "Falló la validación");
        } catch (e) {
            toast.error(e.response?.data?.detail || "Error testeando");
            setTestResult({ ok: false, error: e.message });
        } finally {
            setBusy(false);
        }
    };

    const save = async () => {
        if (!form.mt5_login || !form.mt5_password || !form.mt5_server) {
            toast.error("Login, password y servidor son obligatorios");
            return;
        }
        setBusy(true);
        try {
            const r = await apiPost("/users/me/broker", {
                ...form,
                mt5_login: parseInt(form.mt5_login, 10),
            });
            if (r.data?.ok) {
                toast.success("Credenciales guardadas. Ya podés arrancar el bot.");
                setForm((p) => ({ ...p, mt5_password: "" }));
                setTestResult(null);
                refresh();
            }
        } catch (e) {
            toast.error(e.response?.data?.detail || "No se pudo guardar");
        } finally {
            setBusy(false);
        }
    };

    const remove = async () => {
        setConfirmDelete(false);
        setBusy(true);
        try {
            await apiDelete("/users/me/broker");
            toast.success("Broker desconectado");
            setBroker(null);
            refresh();
        } catch (e) {
            toast.error("Error desconectando");
        } finally {
            setBusy(false);
        }
    };

    const startBot = async () => {
        setBusy(true);
        try {
            const r = await apiPost("/users/me/bot/start", {});
            toast.success(
                isAdmin
                    ? "Bot admin activado (sin trial)"
                    : "Bot activado · 24h de trial 🚀"
            );
            refresh();
        } catch (e) {
            const detail = e.response?.data?.detail;
            const status = e.response?.status;
            if (status === 503) toast.error("Cupo lleno: " + (detail || ""));
            else if (status === 412) toast.error("Conectá tu broker primero");
            else if (status === 409) toast.info("Tu bot ya está corriendo");
            else toast.error(detail || "No se pudo arrancar");
        } finally {
            setBusy(false);
        }
    };

    const stopBot = async () => {
        setBusy(true);
        try {
            await apiPost("/users/me/bot/stop", {});
            toast.success("Bot detenido");
            refresh();
        } catch (e) {
            toast.error(e.response?.data?.detail || "Error deteniendo");
        } finally {
            setBusy(false);
        }
    };

    if (loading) {
        return (
            <section className="px-6 lg:px-10 py-8">
                <div className="max-w-[1200px] mx-auto">
                    <SectionHeader code="MI CUENTA" title="Mi cuenta" subtitle="Cargando..." />
                    <SkeletonPanel rows={5} />
                </div>
            </section>
        );
    }

    return (
        <section className="px-6 lg:px-10 py-8" data-testid="page-myaccount">
            <div className="max-w-[1200px] mx-auto">
                <SectionHeader
                    code="MI CUENTA"
                    title={`Hola ${user?.display_name || user?.email?.split("@")[0]}`}
                    subtitle={
                        isAdmin
                            ? "Sos admin. Acá podés conectar tu propio broker (no afecta el bot global)."
                            : "Conectá tu cuenta XM y arrancá el bot. Trial de 24h gratis."
                    }
                    action={
                        <button
                            type="button"
                            onClick={refresh}
                            className="btn-sharp flex items-center gap-2"
                        >
                            <RefreshCcw size={12} />
                            Refrescar
                        </button>
                    }
                />

                {/* Slot info global */}
                {slots && !isAdmin ? (
                    <div
                        className="panel p-4 mb-4 flex items-center justify-between gap-4 flex-wrap"
                        style={{
                            background: slots.available > 0
                                ? "rgba(16,185,129,0.05)"
                                : "rgba(239,68,68,0.05)",
                            borderColor: slots.available > 0 ? "var(--green)" : "var(--red)",
                        }}
                    >
                        <div className="flex items-center gap-3">
                            <Clock size={16} className={slots.available > 0 ? "text-[var(--green-bright)]" : "text-[var(--red)]"} />
                            <div className="text-xs font-mono">
                                <span className={`font-bold ${slots.available > 0 ? "text-[var(--green-bright)]" : "text-[var(--red)]"}`}>
                                    {slots.active}/{slots.max_concurrent}
                                </span>{" "}
                                bots activos · {slots.available} cupo{slots.available !== 1 ? "s" : ""} libre{slots.available !== 1 ? "s" : ""}
                            </div>
                        </div>
                        <div className="text-[11px] text-[var(--text-faint)]">
                            Trial: {slots.trial_hours}h · Para extender, tu admin debe activarte manualmente.
                        </div>
                    </div>
                ) : null}

                {/* Bot status card */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-4">
                    <KpiCard
                        label="Estado del bot"
                        value={
                            bot?.running
                                ? bot.trial_expired
                                    ? "EXPIRADO"
                                    : "ACTIVO"
                                : "DETENIDO"
                        }
                        sublabel={
                            bot?.running
                                ? bot.is_admin
                                    ? "sin límite de trial"
                                    : bot.is_paid
                                    ? "cuenta paga"
                                    : "trial 24h"
                                : "presioná Iniciar"
                        }
                        color={
                            bot?.running
                                ? bot.trial_expired
                                    ? "red"
                                    : "green"
                                : "white"
                        }
                        icon={bot?.running ? PlayCircle : PauseCircle}
                    />
                    <KpiCard
                        label="Tiempo restante"
                        value={
                            bot?.is_admin
                                ? "∞"
                                : bot?.trial_seconds_remaining != null
                                ? formatRemaining(bot.trial_seconds_remaining)
                                : "—"
                        }
                        sublabel={
                            bot?.is_admin
                                ? "admin · ilimitado"
                                : bot?.trial_end_at
                                ? "vence " + new Date(bot.trial_end_at).toLocaleString("es-AR")
                                : "no aplica"
                        }
                        icon={Clock}
                        color={
                            bot?.is_admin
                                ? "green"
                                : bot?.trial_seconds_remaining != null && bot.trial_seconds_remaining < 3600
                                ? "amber"
                                : "white"
                        }
                    />
                    <div className="panel p-4 flex flex-col justify-between">
                        <div className="kicker mb-2">CONTROL</div>
                        {bot?.running ? (
                            <button
                                type="button"
                                onClick={stopBot}
                                disabled={busy}
                                className="btn-sharp danger w-full flex items-center justify-center gap-2"
                                data-testid="my-bot-stop"
                            >
                                {busy ? <Loader2 size={14} className="animate-spin" /> : <PauseCircle size={14} />}
                                Detener bot
                            </button>
                        ) : (
                            <button
                                type="button"
                                onClick={startBot}
                                disabled={busy || (!broker && !isAdmin)}
                                className="btn-sharp success w-full flex items-center justify-center gap-2"
                                title={!broker && !isAdmin ? "Conectá tu broker primero" : ""}
                                data-testid="my-bot-start"
                            >
                                {busy ? <Loader2 size={14} className="animate-spin" /> : <PlayCircle size={14} />}
                                Iniciar bot
                            </button>
                        )}
                    </div>
                </div>

                {/* Broker connection */}
                <div className="panel p-5 mb-4" data-testid="broker-card">
                    <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                        <div className="flex items-center gap-2">
                            <KeyRound size={14} className="text-[var(--green-bright)]" />
                            <span className="kicker">CONEXIÓN MT5</span>
                            {broker ? (
                                <span className="kicker text-[var(--green-bright)] ml-2">
                                    ● CONECTADA
                                </span>
                            ) : (
                                <span className="kicker text-[var(--text-faint)] ml-2">
                                    ○ NO CONECTADA
                                </span>
                            )}
                        </div>
                        {broker ? (
                            <button
                                type="button"
                                onClick={() => setConfirmDelete(true)}
                                disabled={busy}
                                className="btn-sharp text-[10px] flex items-center gap-1"
                            >
                                <Trash2 size={11} />
                                Desconectar
                            </button>
                        ) : null}
                    </div>

                    {broker ? (
                        <div className="space-y-2 text-xs font-mono">
                            <div className="flex items-center gap-2">
                                <span className="text-[var(--text-faint)] w-24">Broker:</span>
                                <span>{broker.broker?.toUpperCase() || "MT5"}</span>
                                {broker.is_demo ? (
                                    <span className="kicker text-[var(--blue)]">· DEMO</span>
                                ) : (
                                    <span className="kicker text-[var(--amber)]">· REAL</span>
                                )}
                            </div>
                            <div className="flex items-center gap-2">
                                <span className="text-[var(--text-faint)] w-24">Login:</span>
                                <span>{broker.mt5_login}</span>
                            </div>
                            <div className="flex items-center gap-2">
                                <span className="text-[var(--text-faint)] w-24">Servidor:</span>
                                <span>{broker.mt5_server}</span>
                            </div>
                            <div className="flex items-center gap-2">
                                <span className="text-[var(--text-faint)] w-24">Último test:</span>
                                <span>
                                    {broker.last_test_at
                                        ? broker.last_test_ok
                                            ? <CheckCircle2 size={12} className="inline text-[var(--green)]" />
                                            : <XCircle size={12} className="inline text-[var(--red)]" />
                                        : "—"}
                                    {broker.last_test_at
                                        ? " " + new Date(broker.last_test_at).toLocaleString("es-AR")
                                        : ""}
                                </span>
                            </div>
                            <div className="text-[10px] text-[var(--text-faint)] mt-2 italic">
                                Tu password está cifrada con AES-256-GCM. Nunca se devuelve al cliente.
                            </div>
                        </div>
                    ) : (
                        <div className="space-y-3">
                            <p className="text-xs text-[var(--text-dim)]">
                                Conectá tu cuenta MT5. Soportamos XM Global hoy. Si no
                                tenés cuenta:
                            </p>
                            <ReferralBanner variant="compact" />
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
                                <Field label="Login MT5" hint="número de cuenta XM">
                                    <input
                                        type="number"
                                        value={form.mt5_login}
                                        onChange={(e) => updateField("mt5_login", e.target.value)}
                                        className="input-sharp"
                                        placeholder="309780622"
                                        data-testid="broker-login"
                                    />
                                </Field>
                                <Field label="Servidor MT5" hint="ej. XMGlobal-MT5 6">
                                    <input
                                        list="xm-servers"
                                        value={form.mt5_server}
                                        onChange={(e) => updateField("mt5_server", e.target.value)}
                                        className="input-sharp"
                                        data-testid="broker-server"
                                    />
                                    <datalist id="xm-servers">
                                        {XM_SERVERS.map((s) => <option key={s} value={s} />)}
                                    </datalist>
                                </Field>
                                <Field label="Password" hint="se cifra antes de guardar">
                                    <div className="relative">
                                        <input
                                            type={showPwd ? "text" : "password"}
                                            value={form.mt5_password}
                                            onChange={(e) => updateField("mt5_password", e.target.value)}
                                            className="input-sharp pr-10"
                                            placeholder="••••••••"
                                            data-testid="broker-password"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => setShowPwd((v) => !v)}
                                            className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-faint)]"
                                            tabIndex={-1}
                                        >
                                            {showPwd ? <EyeOff size={12} /> : <Eye size={12} />}
                                        </button>
                                    </div>
                                </Field>
                                <Field label="Tipo de cuenta" hint="DEMO recomendado para empezar">
                                    <select
                                        value={form.is_demo ? "demo" : "real"}
                                        onChange={(e) => updateField("is_demo", e.target.value === "demo")}
                                        className="input-sharp"
                                    >
                                        <option value="demo">DEMO ($100k virtuales)</option>
                                        <option value="real">REAL ⚠ dinero real</option>
                                    </select>
                                </Field>
                            </div>

                            {testResult ? (
                                <div
                                    className="text-xs p-2 border-l-2 mt-2"
                                    style={{
                                        borderColor: testResult.ok ? "var(--green)" : "var(--red)",
                                        background: testResult.ok ? "rgba(16,185,129,0.05)" : "rgba(239,68,68,0.05)",
                                    }}
                                >
                                    {testResult.ok ? (
                                        <>
                                            <CheckCircle2 size={12} className="inline mr-1 text-[var(--green)]" />
                                            {testResult.note || "Validación OK"}
                                            {testResult.warning && (
                                                <div className="text-[var(--amber)] mt-1">⚠ {testResult.warning}</div>
                                            )}
                                        </>
                                    ) : (
                                        <>
                                            <XCircle size={12} className="inline mr-1 text-[var(--red)]" />
                                            {testResult.error}
                                        </>
                                    )}
                                </div>
                            ) : null}

                            <div className="flex gap-2 mt-2">
                                <button
                                    type="button"
                                    onClick={test}
                                    disabled={busy}
                                    className="btn-sharp flex items-center gap-2"
                                >
                                    {busy ? <Loader2 size={12} className="animate-spin" /> : <Server size={12} />}
                                    Probar conexión
                                </button>
                                <button
                                    type="button"
                                    onClick={save}
                                    disabled={busy || !testResult?.ok}
                                    className="btn-sharp primary flex items-center gap-2"
                                    title={!testResult?.ok ? "Probá la conexión primero" : ""}
                                >
                                    <Save size={12} />
                                    Guardar credenciales
                                </button>
                            </div>
                        </div>
                    )}
                </div>

                {/* Logs viewer — solo si bot está running y broker conectado */}
                {(broker || bot?.running) ? (
                    <div className="panel p-4" data-testid="logs-card">
                        <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
                            <div className="flex items-center gap-2">
                                <Terminal size={14} className="text-[var(--green)]" />
                                <span className="kicker">LOGS DE TU BOT</span>
                                {bot?.running ? (
                                    <span className="kicker text-[var(--green-bright)]">
                                        ● PROCESO {bot?.run_id ? `RUN ${String(bot.run_id).slice(-6)}` : ""}
                                    </span>
                                ) : null}
                            </div>
                            <div className="flex items-center gap-2">
                                <select
                                    value={logsWhich}
                                    onChange={(e) => {
                                        setLogsWhich(e.target.value);
                                        setLogs("");
                                    }}
                                    className="input-sharp text-[10px] py-1 px-2"
                                >
                                    <option value="stdout">stdout</option>
                                    <option value="stderr">stderr</option>
                                </select>
                                <button
                                    type="button"
                                    onClick={() => setShowLogs((s) => !s)}
                                    className="btn-sharp text-[10px] flex items-center gap-1"
                                >
                                    <FileText size={11} />
                                    {showLogs ? "Ocultar" : "Ver logs"}
                                </button>
                                {showLogs ? (
                                    <button
                                        type="button"
                                        onClick={fetchLogs}
                                        className="btn-sharp text-[10px]"
                                        title="Refrescar"
                                    >
                                        <RefreshCcw size={11} />
                                    </button>
                                ) : null}
                            </div>
                        </div>
                        {showLogs ? (
                            <pre
                                className="text-[10px] font-mono p-3 overflow-auto"
                                style={{
                                    background: "#000",
                                    color: "var(--text-dim)",
                                    maxHeight: 400,
                                    border: "1px solid var(--border)",
                                    whiteSpace: "pre-wrap",
                                    wordBreak: "break-all",
                                }}
                                data-testid="logs-content"
                            >
                                {logs || "(cargando...)"}
                            </pre>
                        ) : (
                            <div className="text-[11px] text-[var(--text-faint)]">
                                Click "Ver logs" para abrir el visor de output del bot
                                (refresca cada 5s automáticamente).
                            </div>
                        )}
                    </div>
                ) : null}

                {/* Roadmap FASE 3 — ahora ya está implementada */}
                <div
                    className="panel p-4 mt-4 border-l-2 text-xs"
                    style={{
                        borderLeftColor: "var(--green)",
                        background: "rgba(16,185,129,0.04)",
                    }}
                >
                    <div className="flex items-start gap-2">
                        <CheckCircle2 size={14} className="text-[var(--green)] mt-0.5" />
                        <div>
                            <div className="font-bold text-[var(--green-bright)] kicker mb-1">
                                FASE 3 ACTIVA — TU BOT OPERA EN TU CUENTA
                            </div>
                            <p className="text-[var(--text-dim)] leading-relaxed">
                                Cuando arrancás el bot, se levanta un proceso dedicado con
                                Wine + MT5 + Python en tu propio prefix isolado. Operará
                                con tus credenciales hasta que se acabe el trial (24h) o
                                vos lo detengas. Los trades van a TU cuenta XM, no a la
                                del admin.
                            </p>
                        </div>
                    </div>
                </div>
            </div>

            <WarningModal
                open={confirmDelete}
                onOpenChange={setConfirmDelete}
                title="¿Desconectar tu broker?"
                body={
                    <div className="space-y-2 text-sm">
                        <p>
                            Vamos a borrar tus credenciales MT5 cifradas. Si tu bot
                            está corriendo, también se va a detener.
                        </p>
                        <p className="text-[var(--text-faint)]">
                            Podés volver a conectarlo cuando quieras.
                        </p>
                    </div>
                }
                confirmLabel="Sí, desconectar"
                cancelLabel="Cancelar"
                danger
                onConfirm={remove}
            />
        </section>
    );
}

function Field({ label, hint, children }) {
    return (
        <div>
            <label className="kicker block mb-1">{label}</label>
            {children}
            {hint ? (
                <div className="text-[10px] text-[var(--text-faint)] mt-1">{hint}</div>
            ) : null}
        </div>
    );
}
