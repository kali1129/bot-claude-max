// MyAccount — página personal del usuario logueado.
//
// FASE 2 (multi-cuenta): el usuario puede conectar UNA cuenta DEMO + UNA
// cuenta REAL al mismo tiempo. El bot opera con la que está marcada como
// "activa". Botón "Switch" intercambia cuál usa, con warning forzado al
// pasar a REAL (checkbox "entiendo que opero con dinero real").
//
// Layout:
//   - Banner de slots
//   - Bot status / control (start/stop)
//   - Lista de cuentas conectadas (cards demo/real con badges + botones)
//   - Form "Agregar cuenta" (alterna entre demo/real según lo que falta)
//   - Logs viewer
//   - Footer info FASE 3

import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import {
    KeyRound, Server, Eye, EyeOff, Save, Trash2, PlayCircle,
    PauseCircle, Clock, AlertTriangle, Loader2,
    CheckCircle2, XCircle, RefreshCcw, Terminal, FileText,
    ArrowRightLeft, FlaskConical, DollarSign, Sparkles,
} from "lucide-react";

import { apiGet, apiPost, apiDelete } from "@/lib/api";
import { useAuth } from "@/lib/AuthProvider";

import SectionHeader from "@/components/atoms/SectionHeader";
import KpiCard from "@/components/atoms/KpiCard";
import SkeletonPanel from "@/components/atoms/SkeletonPanel";
import WarningModal from "@/components/atoms/WarningModal";
import ReferralBanner from "@/components/atoms/ReferralBanner";

const XM_SERVERS_DEMO = [
    "XMGlobal-Demo",
    "XMGlobal-MT5 6",
    "XMGlobal-MT5 7",
];
const XM_SERVERS_REAL = [
    "XMGlobal-Real",
    "XMGlobal-Real 36",
    "XMGlobal-MT5",
    "XMGlobal-MT5 2",
    "XMGlobal-MT5 3",
    "XMGlobal-MT5 4",
    "XMGlobal-MT5 5",
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
    // brokerData = { accounts: [], active: null, has_creds: false }
    const [brokerData, setBrokerData] = useState({ accounts: [], active: null, has_creds: false });
    const [bot, setBot] = useState(null);
    const [slots, setSlots] = useState(null);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);

    // Form state — agregar cuenta nueva
    const [showAddForm, setShowAddForm] = useState(false);
    const [form, setForm] = useState({
        mt5_login: "",
        mt5_password: "",
        mt5_server: "XMGlobal-Demo",
        mt5_path: "",
        is_demo: true,
    });
    const [showPwd, setShowPwd] = useState(false);
    const [testResult, setTestResult] = useState(null);

    // Switch confirmation modal
    const [switchTarget, setSwitchTarget] = useState(null);  // {is_demo} o null

    // Delete confirmation modal
    const [deleteTarget, setDeleteTarget] = useState(null);  // {is_demo, mt5_login} o null

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
                setBrokerData(b.value.data || { accounts: [], active: null, has_creds: false });
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

    const accounts = brokerData.accounts || [];
    const hasDemo = accounts.some((a) => a.is_demo);
    const hasReal = accounts.some((a) => !a.is_demo);
    const active = brokerData.active;

    const updateField = (k, v) => {
        setForm((p) => {
            const next = { ...p, [k]: v };
            // Auto-switch server hint cuando se cambia is_demo
            if (k === "is_demo") {
                if (v && (!p.mt5_server || p.mt5_server.toLowerCase().includes("real"))) {
                    next.mt5_server = "XMGlobal-Demo";
                } else if (!v && p.mt5_server && p.mt5_server.toLowerCase().includes("demo")) {
                    next.mt5_server = "XMGlobal-Real";
                }
            }
            return next;
        });
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
        // Si guarda una REAL como nueva cuenta, requerir confirmación
        if (!form.is_demo) {
            const ok = window.confirm(
                "⚠ Estás guardando credenciales de una cuenta REAL.\n\n" +
                "Si después la activás (botón Switch), el bot operará con DINERO REAL.\n\n" +
                "¿Continuar guardando?"
            );
            if (!ok) return;
        }
        setBusy(true);
        try {
            const r = await apiPost("/users/me/broker", {
                ...form,
                mt5_login: parseInt(form.mt5_login, 10),
            });
            if (r.data?.ok) {
                toast.success(
                    accounts.length === 0
                        ? "Credenciales guardadas y activas. Ya podés arrancar el bot."
                        : "Credenciales guardadas (NO activas — usá Switch para que el bot las use)."
                );
                setForm({
                    mt5_login: "",
                    mt5_password: "",
                    mt5_server: "XMGlobal-Demo",
                    mt5_path: "",
                    is_demo: true,
                });
                setTestResult(null);
                setShowAddForm(false);
                refresh();
            }
        } catch (e) {
            toast.error(e.response?.data?.detail || "No se pudo guardar");
        } finally {
            setBusy(false);
        }
    };

    const removeAccount = async () => {
        if (!deleteTarget) return;
        setBusy(true);
        try {
            const qs = deleteTarget.is_demo != null ? `?is_demo=${deleteTarget.is_demo}` : "";
            await apiDelete(`/users/me/broker${qs}`);
            toast.success(
                `Cuenta ${deleteTarget.is_demo ? "DEMO" : "REAL"} desconectada`
            );
            setDeleteTarget(null);
            refresh();
        } catch (e) {
            toast.error(e.response?.data?.detail || "Error desconectando");
        } finally {
            setBusy(false);
        }
    };

    const doSwitch = async () => {
        if (!switchTarget) return;
        // Para REAL, el modal ya forzó el checkbox; mandamos confirm_real=true.
        // Para DEMO no hace falta.
        const confirmReal = !switchTarget.is_demo;  // implícito por haber clickeado Confirm
        setBusy(true);
        try {
            const r = await apiPost("/users/me/broker/switch", {
                is_demo: switchTarget.is_demo,
                confirm_real: confirmReal,
            });
            const data = r.data;
            if (data?.ok) {
                toast.success(
                    `Activada cuenta ${switchTarget.is_demo ? "DEMO" : "REAL"}` +
                    (data.was_running ? (data.restarted ? " · Bot reiniciado ✓" : " · ⚠ Bot no se pudo reiniciar") : "")
                );
                setSwitchTarget(null);
                refresh();
            }
        } catch (e) {
            toast.error(e.response?.data?.detail || "No se pudo cambiar la cuenta");
        } finally {
            setBusy(false);
        }
    };

    const startBot = async () => {
        setBusy(true);
        try {
            await apiPost("/users/me/bot/start", {});
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
                            : "Conectá tu cuenta XM (demo + real). El bot opera con la que actives."
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
                                disabled={busy || (!active && !isAdmin)}
                                className="btn-sharp success w-full flex items-center justify-center gap-2"
                                title={!active && !isAdmin ? "Conectá y activá una cuenta primero" : ""}
                                data-testid="my-bot-start"
                            >
                                {busy ? <Loader2 size={14} className="animate-spin" /> : <PlayCircle size={14} />}
                                Iniciar bot
                            </button>
                        )}
                    </div>
                </div>

                {/* Cuenta activa highlight (si hay alguna conectada) */}
                {active ? (
                    <div
                        className="panel p-3 mb-4 flex items-center gap-3 flex-wrap"
                        style={{
                            borderColor: active.is_demo ? "var(--blue)" : "var(--amber)",
                            background: active.is_demo
                                ? "rgba(59,130,246,0.05)"
                                : "rgba(245,158,11,0.05)",
                        }}
                    >
                        <Sparkles size={14} className={active.is_demo ? "text-[var(--blue)]" : "text-[var(--amber)]"} />
                        <div className="text-xs font-mono flex-1">
                            <span className="text-[var(--text-faint)]">El bot va a operar con:</span>{" "}
                            <span className="font-bold">
                                {active.is_demo ? "📊 DEMO" : "💰 REAL"}
                            </span>{" "}
                            <span className="text-[var(--text-dim)]">
                                · login {active.mt5_login} · {active.mt5_server}
                            </span>
                        </div>
                        {!active.is_demo ? (
                            <span className="kicker text-[var(--amber)]">⚠ DINERO REAL</span>
                        ) : null}
                    </div>
                ) : null}

                {/* Lista de cuentas conectadas */}
                <div className="panel p-5 mb-4" data-testid="broker-accounts-card">
                    <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                        <div className="flex items-center gap-2">
                            <KeyRound size={14} className="text-[var(--green-bright)]" />
                            <span className="kicker">CUENTAS MT5 CONECTADAS</span>
                            <span className="kicker text-[var(--text-faint)]">
                                {accounts.length}/2
                            </span>
                        </div>
                        {accounts.length < 2 && !showAddForm ? (
                            <button
                                type="button"
                                onClick={() => {
                                    // Default al tipo que falta
                                    const defaultDemo = !hasDemo;
                                    setForm({
                                        mt5_login: "",
                                        mt5_password: "",
                                        mt5_server: defaultDemo ? "XMGlobal-Demo" : "XMGlobal-Real",
                                        mt5_path: "",
                                        is_demo: defaultDemo,
                                    });
                                    setShowAddForm(true);
                                    setTestResult(null);
                                }}
                                className="btn-sharp primary text-[10px] flex items-center gap-1"
                                data-testid="add-account-btn"
                            >
                                + Agregar {!hasDemo && !hasReal ? "primera cuenta" : !hasDemo ? "DEMO" : "REAL"}
                            </button>
                        ) : null}
                    </div>

                    {accounts.length === 0 && !showAddForm ? (
                        <div className="space-y-3 py-3">
                            <p className="text-xs text-[var(--text-dim)]">
                                Aún no conectaste ninguna cuenta. Conectá una cuenta XM
                                (DEMO recomendado para empezar). Si no tenés cuenta:
                            </p>
                            <ReferralBanner variant="compact" />
                        </div>
                    ) : null}

                    {/* Cards de cuentas */}
                    {accounts.length > 0 ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
                            {accounts.map((acc) => (
                                <AccountCard
                                    key={acc.id || `${acc.is_demo}_${acc.mt5_login}`}
                                    account={acc}
                                    isOnlyAccount={accounts.length === 1}
                                    busy={busy}
                                    onSwitch={() => {
                                        setSwitchTarget({ is_demo: acc.is_demo });
                                    }}
                                    onDelete={() => setDeleteTarget({
                                        is_demo: acc.is_demo,
                                        mt5_login: acc.mt5_login,
                                    })}
                                />
                            ))}
                        </div>
                    ) : null}

                    {/* Form agregar */}
                    {showAddForm ? (
                        <div
                            className="border-t pt-4 mt-2"
                            style={{ borderColor: "var(--border)" }}
                        >
                            <div className="flex items-center justify-between mb-3">
                                <span className="kicker">
                                    AGREGAR CUENTA {form.is_demo ? "DEMO 📊" : "REAL 💰"}
                                </span>
                                <button
                                    type="button"
                                    onClick={() => {
                                        setShowAddForm(false);
                                        setTestResult(null);
                                    }}
                                    className="btn-sharp text-[10px]"
                                >
                                    Cancelar
                                </button>
                            </div>

                            {/* Hint saldos realistas - solo cuando es DEMO */}
                            {form.is_demo ? (
                                <div
                                    className="text-[11px] p-3 mb-3 border-l-2"
                                    style={{
                                        borderColor: "var(--blue)",
                                        background: "rgba(59,130,246,0.05)",
                                    }}
                                >
                                    <div className="flex items-start gap-2">
                                        <DollarSign size={13} className="text-[var(--blue)] mt-0.5" />
                                        <div>
                                            <div className="kicker text-[var(--blue)] mb-1">
                                                💡 PONÉ UN SALDO REALISTA EN TU DEMO
                                            </div>
                                            <p className="text-[var(--text-dim)] leading-relaxed">
                                                Cuando creás tu cuenta demo en XM, te dejan elegir
                                                el balance virtual. <strong>No pongas $10,000</strong> —
                                                a menos que seas trader pro, eso no es realista. Probá
                                                el bot con un monto que <em>realmente</em> podrías
                                                tener en tu cuenta real:{" "}
                                                <strong className="text-[var(--green-bright)]">
                                                    $100, $200 o $500
                                                </strong>.
                                                Así vas a ver cómo se comporta con tu capital real
                                                antes de pasar a real.
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            ) : null}

                            {/* Warning grande si REAL */}
                            {!form.is_demo ? (
                                <div
                                    className="text-[11px] p-3 mb-3 border-l-2"
                                    style={{
                                        borderColor: "var(--amber)",
                                        background: "rgba(245,158,11,0.05)",
                                    }}
                                >
                                    <div className="flex items-start gap-2">
                                        <AlertTriangle size={13} className="text-[var(--amber)] mt-0.5" />
                                        <div>
                                            <div className="kicker text-[var(--amber)] mb-1">
                                                ⚠ ESTÁS POR GUARDAR UNA CUENTA REAL
                                            </div>
                                            <p className="text-[var(--text-dim)] leading-relaxed">
                                                Guardar las creds NO activa la cuenta automáticamente.
                                                El bot va a seguir operando con la DEMO. Para que opere
                                                con esta cuenta real, después tenés que apretar
                                                <strong> "Switch"</strong> y aceptar el warning.
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            ) : null}

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
                                <Field label="Tipo de cuenta" hint="DEMO recomendado para empezar">
                                    <select
                                        value={form.is_demo ? "demo" : "real"}
                                        onChange={(e) => updateField("is_demo", e.target.value === "demo")}
                                        className="input-sharp"
                                        data-testid="broker-type"
                                    >
                                        <option value="demo">📊 DEMO (sin riesgo, plata virtual)</option>
                                        <option value="real">💰 REAL (⚠ dinero real)</option>
                                    </select>
                                </Field>
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
                                <Field
                                    label="Servidor MT5"
                                    hint={form.is_demo ? "ej. XMGlobal-Demo" : "ej. XMGlobal-Real"}
                                >
                                    <input
                                        list={form.is_demo ? "xm-servers-demo" : "xm-servers-real"}
                                        value={form.mt5_server}
                                        onChange={(e) => updateField("mt5_server", e.target.value)}
                                        className="input-sharp"
                                        data-testid="broker-server"
                                    />
                                    <datalist id="xm-servers-demo">
                                        {XM_SERVERS_DEMO.map((s) => <option key={s} value={s} />)}
                                    </datalist>
                                    <datalist id="xm-servers-real">
                                        {XM_SERVERS_REAL.map((s) => <option key={s} value={s} />)}
                                    </datalist>
                                </Field>
                                <Field label="Password" hint="se cifra con AES-256-GCM">
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

                            <div className="flex gap-2 mt-3 flex-wrap">
                                <button
                                    type="button"
                                    onClick={test}
                                    disabled={busy}
                                    className="btn-sharp flex items-center gap-2"
                                >
                                    {busy ? <Loader2 size={12} className="animate-spin" /> : <FlaskConical size={12} />}
                                    Probar conexión
                                </button>
                                <button
                                    type="button"
                                    onClick={save}
                                    disabled={busy || !testResult?.ok}
                                    className="btn-sharp primary flex items-center gap-2"
                                    title={!testResult?.ok ? "Probá la conexión primero" : ""}
                                    data-testid="broker-save"
                                >
                                    <Save size={12} />
                                    Guardar credenciales
                                </button>
                            </div>
                        </div>
                    ) : null}
                </div>

                {/* Logs viewer — solo si bot está running o tiene broker */}
                {(accounts.length > 0 || bot?.running) ? (
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

                {/* Footer FASE 3 */}
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
                                Wine + MT5 + Python en tu propio prefix isolado. Va a operar
                                con la cuenta que tengas marcada como <strong>activa</strong>.
                                Si hacés switch entre demo y real mientras el bot está
                                corriendo, el bot se reinicia automáticamente apuntando a
                                la nueva cuenta — no quedan trades cruzados.
                            </p>
                        </div>
                    </div>
                </div>
            </div>

            {/* Switch confirmation modal — para REAL fuerza checkbox via prop */}
            <WarningModal
                open={!!switchTarget}
                onOpenChange={(v) => {
                    if (!v) setSwitchTarget(null);
                }}
                title={
                    switchTarget?.is_demo
                        ? "Cambiar a cuenta DEMO"
                        : "⚠ Activar cuenta REAL"
                }
                body={
                    <div className="space-y-3 text-sm">
                        {switchTarget?.is_demo ? (
                            <>
                                <p>
                                    Vas a hacer que el bot opere con tu cuenta <strong>DEMO</strong>.
                                    No hay riesgo — son fondos virtuales.
                                </p>
                                {bot?.running ? (
                                    <p className="text-[var(--amber)] text-[12px]">
                                        El bot está corriendo: se va a reiniciar con la cuenta nueva
                                        (los trades de la cuenta vieja siguen abiertos en su cuenta).
                                    </p>
                                ) : null}
                            </>
                        ) : (
                            <>
                                <div
                                    className="p-3 border-l-2"
                                    style={{
                                        borderColor: "var(--red)",
                                        background: "rgba(239,68,68,0.08)",
                                    }}
                                >
                                    <p className="font-bold text-[var(--red)] mb-1">
                                        🚨 ATENCIÓN — ESTO AFECTA TU DINERO REAL
                                    </p>
                                    <p className="text-[var(--text-dim)] text-[12px]">
                                        Si activás esta cuenta, el bot va a empezar a abrir
                                        órdenes con <strong>tu plata real</strong>. Cualquier
                                        pérdida es real. Asegurate de que:
                                    </p>
                                    <ul className="text-[12px] list-disc ml-4 mt-2 text-[var(--text-dim)]">
                                        <li>Probaste el bot en demo y entendés cómo opera</li>
                                        <li>El balance es uno con el que estás cómodo perdiendo</li>
                                        <li>Tenés stop-loss configurado en el broker como respaldo</li>
                                    </ul>
                                </div>
                                {bot?.running ? (
                                    <p className="text-[var(--amber)] text-[12px]">
                                        Tu bot está corriendo ahora con DEMO. Al cambiar se va a
                                        reiniciar apuntando a la real — los trades demo abiertos
                                        siguen en tu cuenta demo, no se mueven.
                                    </p>
                                ) : null}
                            </>
                        )}
                    </div>
                }
                checkboxText={
                    !switchTarget?.is_demo
                        ? "Entiendo que opero con dinero real y que cualquier pérdida es responsabilidad mía."
                        : null
                }
                confirmLabel={
                    switchTarget?.is_demo
                        ? "Sí, activar DEMO"
                        : "Activar REAL ⚠"
                }
                cancelLabel="Cancelar"
                danger={!switchTarget?.is_demo}
                onConfirm={doSwitch}
            />

            {/* Delete account modal */}
            <WarningModal
                open={!!deleteTarget}
                onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
                title={`¿Desconectar cuenta ${deleteTarget?.is_demo ? "DEMO" : "REAL"}?`}
                body={
                    <div className="space-y-2 text-sm">
                        <p>
                            Vamos a borrar las credenciales de la cuenta{" "}
                            <strong>
                                {deleteTarget?.is_demo ? "DEMO" : "REAL"} #{deleteTarget?.mt5_login}
                            </strong>{" "}
                            (cifradas, no se pueden recuperar).
                        </p>
                        {active && (active.is_demo === deleteTarget?.is_demo) ? (
                            <p className="text-[var(--amber)] text-xs">
                                ⚠ Esta es tu cuenta ACTIVA. Si tu bot está corriendo se
                                detiene. Si tenés otra cuenta conectada, esa pasa a ser
                                la activa automáticamente.
                            </p>
                        ) : null}
                        <p className="text-[var(--text-faint)] text-[11px]">
                            Podés volver a conectarla cuando quieras.
                        </p>
                    </div>
                }
                confirmLabel="Sí, desconectar"
                cancelLabel="Cancelar"
                danger
                onConfirm={removeAccount}
            />
        </section>
    );
}

function AccountCard({ account, isOnlyAccount, busy, onSwitch, onDelete }) {
    const isDemo = account.is_demo;
    const isActive = account.is_active;
    const accentColor = isDemo ? "var(--blue)" : "var(--amber)";
    const bgColor = isDemo
        ? "rgba(59,130,246,0.04)"
        : "rgba(245,158,11,0.04)";

    return (
        <div
            className="panel p-4 relative"
            style={{
                borderColor: isActive ? accentColor : "var(--border)",
                borderWidth: isActive ? 2 : 1,
                background: isActive ? bgColor : "transparent",
            }}
            data-testid={`account-card-${isDemo ? "demo" : "real"}`}
        >
            {isActive ? (
                <div
                    className="absolute -top-2 left-3 px-2 py-0.5 text-[9px] font-bold tracking-wider"
                    style={{
                        background: accentColor,
                        color: "#000",
                    }}
                >
                    ★ ACTIVA — BOT USA ESTA
                </div>
            ) : null}

            <div className="flex items-start justify-between mb-3">
                <div>
                    <div className="flex items-center gap-2 mb-1">
                        <span
                            className="kicker text-base font-black"
                            style={{ color: accentColor }}
                        >
                            {isDemo ? "📊 DEMO" : "💰 REAL"}
                        </span>
                        {!isDemo ? (
                            <span className="kicker text-[var(--amber)] text-[9px]">
                                ⚠ DINERO REAL
                            </span>
                        ) : null}
                    </div>
                    <div className="text-[10px] text-[var(--text-faint)]">
                        Conectada {account.created_at ? new Date(account.created_at).toLocaleDateString("es-AR") : ""}
                    </div>
                </div>
                <button
                    type="button"
                    onClick={onDelete}
                    disabled={busy}
                    className="btn-sharp text-[9px] flex items-center gap-1"
                    title="Desconectar esta cuenta"
                    data-testid={`delete-${isDemo ? "demo" : "real"}`}
                >
                    <Trash2 size={10} />
                </button>
            </div>

            <div className="space-y-1 text-[11px] font-mono">
                <div className="flex">
                    <span className="text-[var(--text-faint)] w-20">Login:</span>
                    <span>{account.mt5_login}</span>
                </div>
                <div className="flex">
                    <span className="text-[var(--text-faint)] w-20">Servidor:</span>
                    <span className="text-[10px]">{account.mt5_server}</span>
                </div>
                <div className="flex items-center">
                    <span className="text-[var(--text-faint)] w-20">Test:</span>
                    {account.last_test_at ? (
                        <>
                            {account.last_test_ok ? (
                                <CheckCircle2 size={11} className="inline mr-1 text-[var(--green)]" />
                            ) : (
                                <XCircle size={11} className="inline mr-1 text-[var(--red)]" />
                            )}
                            <span className="text-[10px]">
                                {new Date(account.last_test_at).toLocaleString("es-AR")}
                            </span>
                        </>
                    ) : (
                        <span className="text-[var(--text-faint)] text-[10px]">no testeada</span>
                    )}
                </div>
            </div>

            {/* Switch button */}
            {!isActive ? (
                <button
                    type="button"
                    onClick={onSwitch}
                    disabled={busy || isOnlyAccount}
                    className="btn-sharp w-full mt-3 flex items-center justify-center gap-2 text-[11px]"
                    style={{
                        background: accentColor,
                        color: "#000",
                        fontWeight: "bold",
                    }}
                    title={isOnlyAccount ? "Necesitás otra cuenta para hacer switch" : ""}
                    data-testid={`switch-to-${isDemo ? "demo" : "real"}`}
                >
                    <ArrowRightLeft size={12} />
                    {isDemo ? "Activar esta DEMO" : "⚠ Activar esta REAL"}
                </button>
            ) : (
                <div
                    className="text-center mt-3 py-2 text-[11px] font-bold"
                    style={{
                        background: accentColor,
                        color: "#000",
                    }}
                >
                    ✓ EL BOT USA ESTA CUENTA
                </div>
            )}
        </div>
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
