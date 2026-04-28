import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
    Cog,
    KeyRound,
    Cpu,
    PlayCircle,
    StopCircle,
    RotateCw,
    Bot,
    Save,
    Eye,
    EyeOff,
    AlertTriangle,
    CheckCircle2,
    XCircle,
    MessageCircle,
    Send,
} from "lucide-react";

const TOKEN = process.env.REACT_APP_DASHBOARD_TOKEN || "";
const authHeaders = TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};


function Section({ icon, title, children }) {
    const Icon = icon;
    return (
        <div className="panel p-5 mb-4">
            <div className="flex items-center gap-2 mb-4">
                <Icon size={16} className="text-[var(--blue)]" />
                <span className="kicker">{title}</span>
            </div>
            {children}
        </div>
    );
}


function Field({ label, children, hint }) {
    return (
        <div>
            <div className="kicker text-[var(--text-faint)] mb-1">{label}</div>
            {children}
            {hint && (
                <div className="text-[10px] text-[var(--text-faint)] font-mono mt-1">
                    {hint}
                </div>
            )}
        </div>
    );
}


// --------------------------- BOT CONFIG ---------------------------

function BotConfigCard({ api, config, onSaved }) {
    const [form, setForm] = useState({
        TRADING_MODE: "",
        MAX_LOTS_PER_TRADE: "",
        MT5_MAGIC: "",
        DASHBOARD_URL: "",
        SYNC_INTERVAL_SECONDS: "",
    });
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (config) {
            setForm({
                TRADING_MODE: config.TRADING_MODE || "demo",
                MAX_LOTS_PER_TRADE: config.MAX_LOTS_PER_TRADE || "0.5",
                MT5_MAGIC: config.MT5_MAGIC || "20260427",
                DASHBOARD_URL: config.DASHBOARD_URL || "http://localhost:8010",
                SYNC_INTERVAL_SECONDS: config.SYNC_INTERVAL_SECONDS || "30",
            });
        }
    }, [config]);

    const save = async () => {
        try {
            setSaving(true);
            const r = await axios.post(`${api}/bot/config`,
                { updates: form },
                { headers: authHeaders });
            if (r.data?.ok) {
                toast.success("Configuración guardada. Reinicia el bot para aplicar.");
                onSaved?.();
            } else {
                toast.error(`Error: ${r.data?.reason}`);
            }
        } catch (e) {
            toast.error(`Error: ${e.message}`);
        } finally {
            setSaving(false);
        }
    };

    return (
        <Section icon={Cog} title="Configuración del bot">
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
                <Field label="Modo de trading" hint="demo es el default · paper sólo para tests">
                    <select
                        className="input-sharp"
                        value={form.TRADING_MODE}
                        onChange={(e) => setForm({ ...form, TRADING_MODE: e.target.value })}
                    >
                        <option value="demo">demo (MT5 demo real)</option>
                        <option value="paper">paper (sólo simulado, para tests)</option>
                        <option value="live">live (cuenta real ⚠)</option>
                    </select>
                </Field>
                <Field label="Lotaje máximo por trade" hint="cap absoluto, default 0.5">
                    <input className="input-sharp" type="number" step="0.01"
                        value={form.MAX_LOTS_PER_TRADE}
                        onChange={(e) => setForm({ ...form, MAX_LOTS_PER_TRADE: e.target.value })} />
                </Field>
                <Field label="Magic ID" hint="identifica trades del bot en MT5">
                    <input className="input-sharp" type="number"
                        value={form.MT5_MAGIC}
                        onChange={(e) => setForm({ ...form, MT5_MAGIC: e.target.value })} />
                </Field>
                <Field label="URL del backend" hint="dónde el bot postea deals">
                    <input className="input-sharp"
                        value={form.DASHBOARD_URL}
                        onChange={(e) => setForm({ ...form, DASHBOARD_URL: e.target.value })} />
                </Field>
                <Field label="Intervalo del sync (s)" hint="cada cuánto el sync_loop revisa">
                    <input className="input-sharp" type="number" min="10" max="600"
                        value={form.SYNC_INTERVAL_SECONDS}
                        onChange={(e) => setForm({ ...form, SYNC_INTERVAL_SECONDS: e.target.value })} />
                </Field>
            </div>
            <button onClick={save} disabled={saving}
                className="btn-sharp primary flex items-center gap-2">
                <Save size={14} />
                {saving ? "Guardando…" : "Guardar configuración"}
            </button>
            <div className="text-[10px] text-[var(--amber)] font-mono mt-3 stripes-warn p-2">
                ⚠ Las reglas duras del sistema (1% riesgo, 3% diario, R:R 1:2,
                1 posición, blackout horario) NO son editables desde aquí —
                viven en <span className="text-white">_shared/rules.py</span>{" "}
                por diseño.
            </div>
        </Section>
    );
}


// --------------------------- MT5 CREDENTIALS ---------------------------

function MT5CredsCard({ api, currentConfig, onSaved }) {
    const [form, setForm] = useState({
        login: "",
        password: "",
        server: "",
        path: "",
    });
    const [showPwd, setShowPwd] = useState(false);
    const [testing, setTesting] = useState(false);
    const [saving, setSaving] = useState(false);
    const [testResult, setTestResult] = useState(null);

    useEffect(() => {
        if (currentConfig) {
            setForm({
                login: currentConfig.MT5_LOGIN || "",
                password: "",
                server: currentConfig.MT5_SERVER || "",
                path: currentConfig.MT5_PATH || "",
            });
        }
    }, [currentConfig]);

    const test = async () => {
        if (!form.login || !form.password || !form.server) {
            toast.error("Login, password y servidor son obligatorios");
            return;
        }
        try {
            setTesting(true);
            setTestResult(null);
            const r = await axios.post(`${api}/mt5/credentials/test`, form, { timeout: 30000 });
            setTestResult(r.data);
            if (r.data?.ok && r.data?.account) {
                toast.success(`Conectado: cuenta ${r.data.account.login}, balance $${r.data.account.balance}`);
            } else {
                toast.error(`Falló: ${JSON.stringify(r.data?.error || r.data?.reason)}`);
            }
        } catch (e) {
            toast.error(`Error: ${e.message}`);
        } finally {
            setTesting(false);
        }
    };

    const save = async () => {
        if (!testResult?.ok) {
            if (!window.confirm("No has probado las credenciales. ¿Guardar de todas formas?"))
                return;
        }
        try {
            setSaving(true);
            const r = await axios.post(`${api}/mt5/credentials`, form,
                { headers: authHeaders });
            if (r.data?.ok) {
                toast.success("Credenciales guardadas. Reinicia el bot para aplicar.");
                setForm({ ...form, password: "" });
                onSaved?.();
            } else {
                toast.error(`Error: ${r.data?.reason} ${r.data?.detail || ""}`);
            }
        } catch (e) {
            toast.error(`Error: ${e.message}`);
        } finally {
            setSaving(false);
        }
    };

    return (
        <Section icon={KeyRound} title="Credenciales MT5">
            <div className="text-[11px] text-[var(--text-dim)] font-mono mb-4">
                Cambia entre cuentas (demo / real) sin tocar el .env directamente.
                La password se guarda en el archivo .env del bot, que está
                gitignored.
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-4 gap-3 mb-4">
                <Field label="Login (número)">
                    <input className="input-sharp" type="number"
                        value={form.login}
                        onChange={(e) => setForm({ ...form, login: e.target.value })} />
                </Field>
                <Field label="Password">
                    <div className="relative">
                        <input className="input-sharp pr-8"
                            type={showPwd ? "text" : "password"}
                            value={form.password}
                            onChange={(e) => setForm({ ...form, password: e.target.value })}
                            autoComplete="off" />
                        <button type="button"
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-dim)]"
                            onClick={() => setShowPwd((v) => !v)}>
                            {showPwd ? <EyeOff size={14} /> : <Eye size={14} />}
                        </button>
                    </div>
                </Field>
                <Field label="Servidor" hint="ej. XMGlobal-MT5 6 / Demo / Real">
                    <input className="input-sharp"
                        value={form.server}
                        onChange={(e) => setForm({ ...form, server: e.target.value })} />
                </Field>
                <Field label="Path al terminal (opcional)" hint="terminal64.exe">
                    <input className="input-sharp"
                        value={form.path}
                        onChange={(e) => setForm({ ...form, path: e.target.value })} />
                </Field>
            </div>
            <div className="flex gap-2">
                <button onClick={test} disabled={testing}
                    className="btn-sharp flex items-center gap-2">
                    {testing ? "Probando…" : "Probar conexión"}
                </button>
                <button onClick={save} disabled={saving}
                    className="btn-sharp primary flex items-center gap-2">
                    <Save size={14} />
                    {saving ? "Guardando…" : "Guardar"}
                </button>
            </div>
            {testResult && (
                <div className="mt-3 panel p-3">
                    <div className="kicker mb-1">
                        {testResult.ok && testResult.account
                            ? "✓ Conexión exitosa"
                            : "✗ Falló"}
                    </div>
                    <pre className="codeblock text-[10px]">
                        {JSON.stringify(testResult, null, 2)}
                    </pre>
                </div>
            )}
        </Section>
    );
}


// --------------------------- PROCESS MANAGER ---------------------------

function ProcessesCard({ api, onChange }) {
    const [processes, setProcesses] = useState([]);
    const [busy, setBusy] = useState({});

    const load = useCallback(async () => {
        try {
            const r = await axios.get(`${api}/process/list`);
            setProcesses(r.data.processes || []);
        } catch (e) {
            console.error(e);
        }
    }, [api]);

    useEffect(() => {
        load();
        const id = setInterval(load, 5000);
        return () => clearInterval(id);
    }, [load]);

    const action = async (name, op) => {
        try {
            setBusy({ ...busy, [name]: op });
            const r = await axios.post(
                `${api}/process/${name}/${op}`,
                {},
                { headers: authHeaders, timeout: 30000 }
            );
            if (r.data?.ok) {
                toast.success(`${name}: ${op} OK${r.data.pid ? ` · pid ${r.data.pid}` : ""}`);
                onChange?.();
            } else {
                toast.error(`${name}: ${r.data?.reason || "error"}`);
            }
            load();
        } catch (e) {
            toast.error(`Error: ${e.message}`);
        } finally {
            setBusy({ ...busy, [name]: null });
        }
    };

    return (
        <Section icon={Cpu} title="Procesos del sistema">
            <div className="space-y-3">
                {processes.map((p) => (
                    <div key={p.name}
                        className="flex items-center justify-between gap-3 panel p-3">
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                                {p.alive ? (
                                    <CheckCircle2 size={14} className="text-[var(--green-bright)]" />
                                ) : (
                                    <XCircle size={14} className="text-[var(--red)]" />
                                )}
                                <span className="font-display font-semibold">{p.name}</span>
                                {p.alive && (
                                    <span className="kicker text-[var(--text-faint)]">
                                        pid {p.pid}
                                    </span>
                                )}
                            </div>
                            <div className="text-[11px] text-[var(--text-dim)] mt-1">
                                {p.description}
                            </div>
                        </div>
                        <div className="flex gap-2 flex-shrink-0">
                            {!p.alive && (
                                <button onClick={() => action(p.name, "start")}
                                    disabled={busy[p.name]}
                                    className="btn-sharp primary flex items-center gap-1">
                                    <PlayCircle size={12} />
                                    Arrancar
                                </button>
                            )}
                            {p.alive && (
                                <>
                                    <button onClick={() => action(p.name, "restart")}
                                        disabled={busy[p.name]}
                                        className="btn-sharp flex items-center gap-1">
                                        <RotateCw size={12} />
                                        Reiniciar
                                    </button>
                                    <button onClick={() => action(p.name, "stop")}
                                        disabled={busy[p.name]}
                                        className="btn-sharp danger flex items-center gap-1">
                                        <StopCircle size={12} />
                                        Detener
                                    </button>
                                </>
                            )}
                        </div>
                    </div>
                ))}
            </div>
        </Section>
    );
}


// --------------------------- SUPERVISOR ---------------------------

function SupervisorCard({ api }) {
    const [info, setInfo] = useState(null);

    const load = useCallback(async () => {
        try {
            const r = await axios.get(`${api}/supervisor`);
            setInfo(r.data);
        } catch (e) {
            console.error(e);
        }
    }, [api]);

    useEffect(() => {
        load();
        const id = setInterval(load, 30000);
        return () => clearInterval(id);
    }, [load]);

    return (
        <Section icon={Bot} title="Supervisor de Claude (agente programado)">
            {!info?.installed ? (
                <div className="text-[var(--text-dim)] text-sm">
                    El supervisor de Claude no está instalado en este equipo.
                    <div className="text-[11px] text-[var(--text-faint)] mt-2 font-mono">
                        Tienes que crearlo desde Claude Code: pídele "crea un agente
                        programado que cada 15 min revise el bot y opere si hay
                        setup A+".
                    </div>
                </div>
            ) : (
                <>
                    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3">
                        <Field label="Estado">
                            <div className={`font-mono text-sm ${info.enabled ? "text-[var(--green-bright)]" : "text-[var(--red)]"}`}>
                                {info.enabled ? "Activo" : "Pausado"}
                            </div>
                        </Field>
                        <Field label="Frecuencia">
                            <div className="font-mono text-sm">{info.cron || "—"}</div>
                        </Field>
                        <Field label="Última ejecución">
                            <div className="font-mono text-xs">{info.last_run_at || "Nunca"}</div>
                        </Field>
                        <Field label="Próxima">
                            <div className="font-mono text-xs">{info.next_run_at || "—"}</div>
                        </Field>
                    </div>
                    <div className="text-[11px] text-[var(--text-dim)]">
                        {info.description}
                    </div>
                    <div className="text-[10px] text-[var(--text-faint)] font-mono mt-3 stripes-warn p-2">
                        ⚠ El supervisor se administra desde Claude Code (sidebar
                        → Scheduled). Pausar / cambiar frecuencia / desinstalar:
                        pídele a Claude que actualice la task <span className="text-white">trading-bot-supervisor</span>.
                    </div>
                </>
            )}
        </Section>
    );
}


// --------------------------- TELEGRAM ---------------------------

function TelegramCard({ api }) {
    const [info, setInfo] = useState(null);
    const [testMsg, setTestMsg] = useState("");
    const [busy, setBusy] = useState(false);

    const load = useCallback(async () => {
        try {
            const r = await axios.get(`${api}/telegram/status`);
            setInfo(r.data);
        } catch (e) {
            console.error(e);
        }
    }, [api]);

    useEffect(() => { load(); }, [load]);

    const sendTest = async () => {
        try {
            setBusy(true);
            const r = await axios.post(`${api}/telegram/test`,
                testMsg ? { text: testMsg } : {},
                { headers: authHeaders });
            if (r.data?.ok) toast.success("Mensaje enviado a Telegram");
            else toast.error(`No enviado: ${r.data?.reason || "error"}`);
        } catch (e) {
            toast.error(`Error: ${e.message}`);
        } finally {
            setBusy(false);
        }
    };

    const sendSummary = async () => {
        try {
            setBusy(true);
            const r = await axios.post(`${api}/telegram/summary`, {},
                { headers: authHeaders });
            if (r.data?.ok) toast.success("Resumen enviado");
            else toast.error(`No enviado: ${r.data?.reason || "error"}`);
        } catch (e) {
            toast.error(`Error: ${e.message}`);
        } finally {
            setBusy(false);
        }
    };

    return (
        <Section icon={MessageCircle} title="Notificaciones Telegram">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4 text-xs">
                <Field label="Estado">
                    <div className={`font-mono ${info?.enabled ? "text-[var(--green-bright)]" : "text-[var(--text-faint)]"}`}>
                        {info?.enabled ? "Activado" : "Desactivado"}
                    </div>
                </Field>
                <Field label="Configurado">
                    <div className={`font-mono ${info?.configured ? "text-[var(--green-bright)]" : "text-[var(--red)]"}`}>
                        {info?.configured ? "Sí" : "No"}
                    </div>
                </Field>
                <Field label="Bot ID">
                    <div className="font-mono text-[var(--text-dim)]">
                        {info?.bot_prefix || "—"}
                    </div>
                </Field>
                <Field label="Chat ID">
                    <div className="font-mono text-[var(--text-dim)]">
                        {info?.chat_id || "—"}
                    </div>
                </Field>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-3">
                <div className="lg:col-span-2">
                    <Field label="Mensaje de prueba (opcional)">
                        <input className="input-sharp"
                            value={testMsg}
                            placeholder="Si lo dejas vacío, envía uno por defecto"
                            onChange={(e) => setTestMsg(e.target.value)} />
                    </Field>
                </div>
                <div className="flex items-end gap-2">
                    <button onClick={sendTest} disabled={busy || !info?.configured}
                        className="btn-sharp primary flex items-center gap-2">
                        <Send size={14} />
                        Enviar prueba
                    </button>
                    <button onClick={sendSummary} disabled={busy || !info?.configured}
                        className="btn-sharp">
                        Enviar resumen
                    </button>
                </div>
            </div>
            <div className="text-[10px] text-[var(--text-faint)] font-mono mt-2">
                El bot envía notificaciones automáticas: trade abierto, trade
                cerrado (con P&L), kill-switch (halt/resume) y alertas
                operativas. Las credenciales se leen del .env (gitignored).
            </div>
        </Section>
    );
}


// --------------------------- MAIN ---------------------------

export default function ConfigPanel({ api, config, onMutated }) {
    return (
        <section id="config" className="border-b border-[var(--border)] px-6 lg:px-10 py-12">
            <div className="mb-6">
                <div className="kicker mb-2">// 02 · CONFIGURACIÓN</div>
                <h2 className="font-display text-3xl font-black tracking-tight">
                    Centro de Configuración
                </h2>
                <p className="text-[var(--text-dim)] text-sm mt-2 max-w-2xl">
                    Todo lo que necesitas modificar — credenciales, modo,
                    procesos, supervisor — desde aquí. Sin tocar archivos.
                </p>
            </div>

            <BotConfigCard api={api} config={config} onSaved={onMutated} />
            <MT5CredsCard api={api} currentConfig={config} onSaved={onMutated} />
            <TelegramCard api={api} />
            <ProcessesCard api={api} onChange={onMutated} />
            <SupervisorCard api={api} />
        </section>
    );
}
