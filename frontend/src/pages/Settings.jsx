// Settings page — Tabs: General · Estrategia · Notificaciones · MT5 · Avanzado
//
// La de avanzado solo aparece si modo=experto (la spec lo pide).

import { useCallback, useEffect, useState } from "react";
import { Save, Send, KeyRound, Cpu, Cog, Bell, Sliders } from "lucide-react";
import { toast } from "sonner";

import { useSettings } from "@/lib/userMode";
import { apiGet, apiPost } from "@/lib/api";

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import StylePresetCard from "@/components/atoms/StylePresetCard";
import SessionSelector from "@/components/atoms/SessionSelector";
import TelegramChatInput from "@/components/atoms/TelegramChatInput";
import WarningModal from "@/components/atoms/WarningModal";
import UserModeBadge from "@/components/atoms/UserModeBadge";
import SectionHeader from "@/components/atoms/SectionHeader";
import ReferralBanner from "@/components/atoms/ReferralBanner";

export default function Settings() {
    const { settings, updateSettings, isExperto, refresh } = useSettings();
    const tabs = [
        { value: "general", label: "Mi Plan", Icon: Sliders },
        { value: "strategy", label: "Estrategia", Icon: Cog },
        { value: "notifications", label: "Notificaciones", Icon: Bell },
        { value: "mt5", label: "Broker (MT5)", Icon: KeyRound },
    ];
    if (isExperto) {
        tabs.push({ value: "advanced", label: "Avanzado", Icon: Cpu });
    }

    return (
        <section className="px-6 lg:px-10 py-8" data-testid="page-settings">
            <div className="max-w-[1400px] mx-auto">
                <SectionHeader
                    code="03 / CONFIGURACIÓN"
                    title="Centro de Configuración"
                    subtitle="Todo lo que necesitás cambiar — sin tocar archivos."
                    action={<UserModeBadge />}
                />

                <Tabs defaultValue="general" className="w-full">
                    <TabsList className="bg-[var(--surface)] border border-[var(--border)] flex flex-wrap h-auto p-0">
                        {tabs.map(({ value, label, Icon }) => (
                            <TabsTrigger
                                key={value}
                                value={value}
                                className="text-xs font-mono px-4 py-2 data-[state=active]:bg-[var(--surface-2)] data-[state=active]:text-[var(--green-bright)] flex items-center gap-2"
                            >
                                <Icon size={12} />
                                {label}
                            </TabsTrigger>
                        ))}
                    </TabsList>

                    <TabsContent value="general" className="mt-4">
                        <GeneralTab
                            settings={settings}
                            updateSettings={updateSettings}
                        />
                    </TabsContent>
                    <TabsContent value="strategy" className="mt-4">
                        <StrategyTab
                            settings={settings}
                            updateSettings={updateSettings}
                        />
                    </TabsContent>
                    <TabsContent value="notifications" className="mt-4">
                        <NotificationsTab
                            settings={settings}
                            updateSettings={updateSettings}
                            refreshSettings={refresh}
                        />
                    </TabsContent>
                    <TabsContent value="mt5" className="mt-4">
                        <MT5Tab />
                    </TabsContent>
                    {isExperto ? (
                        <TabsContent value="advanced" className="mt-4">
                            <AdvancedTab />
                        </TabsContent>
                    ) : null}
                </Tabs>
            </div>
        </section>
    );
}

// =============================================================================
// GENERAL TAB — meta + modo
// =============================================================================
function GeneralTab({ settings, updateSettings }) {
    const [goal, setGoal] = useState(settings?.goal_usd ?? 1500);
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        setGoal(settings?.goal_usd ?? 1500);
    }, [settings?.goal_usd]);

    const numericGoal = Number(goal);
    const validGoal = Number.isFinite(numericGoal) && numericGoal >= 100 && numericGoal <= 1_000_000;

    const save = async () => {
        if (!validGoal) {
            toast.error("La meta tiene que estar entre $100 y $1,000,000");
            return;
        }
        setBusy(true);
        try {
            await updateSettings({ goal_usd: numericGoal });
            toast.success("Meta actualizada");
        } catch (e) {
            toast.error("No se pudo guardar la meta");
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="panel p-6 space-y-5">
            <div>
                <label className="kicker block mb-2">META DE LA CUENTA (USD)</label>
                <div className="flex items-center gap-2 max-w-md">
                    <span className="font-mono text-2xl text-[var(--text-faint)]">$</span>
                    <input
                        type="number"
                        min={100}
                        max={1_000_000}
                        value={goal ?? ""}
                        onChange={(e) => setGoal(e.target.value)}
                        className="input-sharp text-lg font-mono tabular flex-1"
                        placeholder="ej. 1500"
                        data-testid="settings-goal"
                    />
                </div>
                {!validGoal && goal !== "" && goal != null ? (
                    <div className="text-xs text-[var(--red)] mt-2">
                        Tiene que estar entre $100 y $1,000,000.
                    </div>
                ) : null}
                <div className="kicker mt-2 normal-case tracking-normal text-[var(--text-dim)]">
                    El bot ajusta el tamaño de cada operación para llegar a la meta sin volar la cuenta.
                </div>
                <button
                    type="button"
                    onClick={save}
                    disabled={busy || !validGoal}
                    className="btn-sharp primary mt-3 flex items-center gap-2"
                    data-testid="settings-save-goal"
                >
                    <Save size={12} />
                    Guardar meta
                </button>
            </div>
        </div>
    );
}

// =============================================================================
// STRATEGY TAB — estilo + sesiones
// =============================================================================
function StrategyTab({ settings, updateSettings }) {
    const [warnAggressive, setWarnAggressive] = useState(false);
    const [busy, setBusy] = useState(false);
    const styles = settings?.available_styles || {
        conservativo: { risk_pct: 0.5, max_pos: 1, min_rr: 2.0 },
        balanceado: { risk_pct: 1.0, max_pos: 3, min_rr: 2.0 },
        agresivo: { risk_pct: 2.0, max_pos: 5, min_rr: 1.8 },
    };

    const setStyle = async (key) => {
        if (key === "agresivo") {
            setWarnAggressive(true);
            return;
        }
        setBusy(true);
        try {
            await updateSettings({ style: key });
            toast.success(`Estilo cambiado a ${key}`);
        } catch (e) {
            toast.error("No se pudo cambiar el estilo");
        } finally {
            setBusy(false);
        }
    };

    const confirmAggressive = async () => {
        setBusy(true);
        try {
            await updateSettings({ style: "agresivo" });
            toast.success("Modo agresivo activado");
        } catch (e) {
            toast.error("No se pudo cambiar el estilo");
        } finally {
            setBusy(false);
        }
    };

    const setSessions = async (sessions) => {
        setBusy(true);
        try {
            await updateSettings({ sessions });
            toast.success("Sesiones actualizadas");
        } catch (e) {
            toast.error("No se pudo cambiar las sesiones");
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="space-y-6">
            <div className="panel p-6">
                <div className="kicker mb-3">ESTILO DE TRADING</div>
                <p className="text-xs text-[var(--text-dim)] mb-4">
                    Esto define cuánto riesgo toma el bot por cada operación.
                </p>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <StylePresetCard
                        presetKey="conservativo"
                        preset={styles.conservativo}
                        active={settings?.style === "conservativo"}
                        onClick={() => setStyle("conservativo")}
                        disabled={busy}
                    />
                    <StylePresetCard
                        presetKey="balanceado"
                        preset={styles.balanceado}
                        active={settings?.style === "balanceado"}
                        recommended
                        onClick={() => setStyle("balanceado")}
                        disabled={busy}
                    />
                    <StylePresetCard
                        presetKey="agresivo"
                        preset={styles.agresivo}
                        active={settings?.style === "agresivo"}
                        onClick={() => setStyle("agresivo")}
                        disabled={busy}
                    />
                </div>
            </div>

            <div className="panel p-6">
                <div className="kicker mb-3">SESIONES DE MERCADO</div>
                <p className="text-xs text-[var(--text-dim)] mb-4">
                    Cuándo querés que el bot opere. Si dudás, dejá 24/7 — ya filtra los momentos malos.
                </p>
                <SessionSelector
                    value={settings?.sessions || ["24/7"]}
                    onChange={setSessions}
                    disabled={busy}
                />
            </div>

            <WarningModal
                open={warnAggressive}
                onOpenChange={setWarnAggressive}
                title="Espera. Este modo es agresivo."
                body={
                    <div className="space-y-3 text-sm">
                        <p>Con este estilo, el bot va a:</p>
                        <ul className="list-disc list-inside space-y-1 text-[var(--text-dim)]">
                            <li>
                                Arriesgar 2% de tu cuenta por cada operación{" "}
                                <span className="text-[var(--red)]">(4× más que conservativo)</span>
                            </li>
                            <li>Abrir hasta 5 operaciones a la vez</li>
                            <li>Buscar entradas con menos confirmación</li>
                        </ul>
                        <p className="font-semibold mt-3">Recomendación:</p>
                        <p className="text-[var(--text-dim)]">
                            Solo elegí este modo si ya operaste 1+ mes con balanceado o
                            conservativo, esta cuenta NO es plata que necesitás, y
                            aceptás perder hasta el 30% sin entrar en pánico.
                        </p>
                    </div>
                }
                checkboxText="Entiendo el riesgo y acepto la responsabilidad."
                cancelLabel="Cancelar, mejor balanceado"
                confirmLabel="Confirmar agresivo"
                danger
                onConfirm={confirmAggressive}
            />
        </div>
    );
}

// =============================================================================
// NOTIFICATIONS TAB — telegram
// =============================================================================
function NotificationsTab({ settings, updateSettings, refreshSettings }) {
    const [busy, setBusy] = useState(false);
    const enabled = !!settings?.telegram_enabled;
    const chats = settings?.telegram_chat_ids || [];

    const toggle = async () => {
        setBusy(true);
        try {
            await updateSettings({ telegram_enabled: !enabled });
            toast.success(enabled ? "Notificaciones desactivadas" : "Notificaciones activadas");
        } catch (e) {
            toast.error("No se pudo cambiar el estado");
        } finally {
            setBusy(false);
        }
    };

    const sendTest = async () => {
        setBusy(true);
        try {
            await apiPost("/telegram/test", {});
            toast.success("Mensaje de prueba enviado");
        } catch (e) {
            toast.error("No se pudo enviar mensaje de prueba");
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="space-y-4">
            <div className="panel p-6">
                <div className="flex items-center justify-between mb-4 gap-4 flex-wrap">
                    <div>
                        <div className="kicker mb-1">NOTIFICACIONES TELEGRAM</div>
                        <p className="text-xs text-[var(--text-dim)] max-w-md">
                            Avisos cuando el bot abre/cierra operaciones o pasa algo importante.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={toggle}
                        disabled={busy}
                        data-testid="telegram-toggle"
                        className={`btn-sharp ${enabled ? "primary" : ""}`}
                    >
                        {enabled ? "Desactivar" : "Activar"}
                    </button>
                </div>

                <TelegramChatInput chats={chats} onChange={refreshSettings} />

                <div className="mt-4 flex flex-wrap gap-2">
                    <button
                        type="button"
                        onClick={sendTest}
                        disabled={busy || !enabled || chats.length === 0}
                        className="btn-sharp flex items-center gap-2"
                        data-testid="telegram-send-test"
                    >
                        <Send size={12} />
                        Enviar mensaje de prueba
                    </button>
                </div>
            </div>
        </div>
    );
}

// =============================================================================
// MT5 TAB — credenciales con test obligatorio antes de guardar
// =============================================================================
function MT5Tab() {
    const [form, setForm] = useState({ login: "", password: "", server: "", path: "" });
    const [showPwd, setShowPwd] = useState(false);
    const [testing, setTesting] = useState(false);
    const [saving, setSaving] = useState(false);
    const [testResult, setTestResult] = useState(null);

    const valid = !!form.login && !!form.password && !!form.server;

    const test = async () => {
        if (!valid) {
            toast.error("Login, password y servidor son obligatorios");
            return;
        }
        setTesting(true);
        setTestResult(null);
        try {
            const r = await apiPost("/mt5/credentials/test", form, { timeout: 30000 });
            setTestResult(r.data);
            if (r.data?.ok && r.data?.account) {
                toast.success(
                    `Conectado: cuenta ${r.data.account.login}, balance $${r.data.account.balance}`
                );
            } else {
                toast.error(`Falló la conexión`);
            }
        } catch (e) {
            toast.error(`Error: ${e.message}`);
            setTestResult({ ok: false, error: e.message });
        } finally {
            setTesting(false);
        }
    };

    const save = async () => {
        if (!testResult?.ok) {
            toast.error("Probá la conexión primero — solo se guarda si el test devuelve OK");
            return;
        }
        setSaving(true);
        try {
            const r = await apiPost("/mt5/credentials", form);
            if (r.data?.ok) {
                toast.success("Credenciales guardadas. Reiniciá el bot para aplicar.");
                setForm({ ...form, password: "" });
                setTestResult(null);
                // Notificar a otros componentes (BotPanel, ConfigPanel) que el
                // /bot/config se actualizó. Los listeners hacen refetch local.
                window.dispatchEvent(new CustomEvent("botconfig:changed"));
            } else {
                toast.error(`Error: ${r.data?.reason}`);
            }
        } catch (e) {
            // En error mantenemos password (usuario puede reintentar) — pero
            // si fue éxito de red con 4xx, también limpiamos por seguridad.
            const status = e.response?.status;
            if (status && status >= 400 && status < 500) {
                setForm({ ...form, password: "" });
            }
            toast.error(`Error: ${e.message}`);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="space-y-4">
            <ReferralBanner variant="feature" />

            <div className="panel p-6">
                <div className="kicker mb-3">CREDENCIALES MT5</div>
                <p className="text-xs text-[var(--text-dim)] mb-4">
                    Ingresá tu login/password/server. Probá la conexión antes de guardar — el botón Guardar se desbloquea solo si el test pasa.
                </p>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
                    <Field label="Login (número)" required>
                        <input
                            className="input-sharp"
                            type="number"
                            value={form.login}
                            onChange={(e) => setForm({ ...form, login: e.target.value })}
                            data-testid="mt5-login"
                        />
                    </Field>
                    <Field label="Password" required>
                        <div className="relative">
                            <input
                                className="input-sharp pr-10"
                                type={showPwd ? "text" : "password"}
                                value={form.password}
                                onChange={(e) => setForm({ ...form, password: e.target.value })}
                                autoComplete="off"
                                data-testid="mt5-password"
                            />
                            <button
                                type="button"
                                onClick={() => setShowPwd((v) => !v)}
                                className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-dim)] text-xs font-mono"
                                aria-label={showPwd ? "Ocultar" : "Mostrar"}
                            >
                                {showPwd ? "ocultar" : "ver"}
                            </button>
                        </div>
                    </Field>
                    <Field
                        label="Servidor"
                        required
                        hint="ej. XMGlobal-MT5 6 o tu broker"
                    >
                        <input
                            className="input-sharp"
                            value={form.server}
                            onChange={(e) => setForm({ ...form, server: e.target.value })}
                            data-testid="mt5-server"
                        />
                    </Field>
                    <Field
                        label="Path al terminal (opcional)"
                        hint="solo si MT5 no está en la ruta default"
                    >
                        <input
                            className="input-sharp"
                            value={form.path}
                            onChange={(e) => setForm({ ...form, path: e.target.value })}
                        />
                    </Field>
                </div>

                <div className="flex flex-wrap gap-2">
                    <button
                        type="button"
                        onClick={test}
                        disabled={testing || !valid}
                        className="btn-sharp flex items-center gap-2"
                        data-testid="mt5-test"
                    >
                        {testing ? "Probando…" : "Probar conexión"}
                    </button>
                    <button
                        type="button"
                        onClick={save}
                        disabled={saving || !testResult?.ok}
                        className="btn-sharp primary flex items-center gap-2"
                        data-testid="mt5-save"
                    >
                        <Save size={12} />
                        {saving ? "Guardando…" : "Guardar"}
                    </button>
                </div>

                {testResult ? (
                    <div className="mt-4 panel p-4">
                        {testResult.ok ? (
                            <div className="text-[var(--green-bright)] font-mono text-sm">
                                ✓ Conexión exitosa
                                {testResult.account ? (
                                    <div className="mt-2 text-xs text-[var(--text-dim)]">
                                        Cuenta: {testResult.account.login} · Balance: ${testResult.account.balance} · Server: {testResult.account.server}
                                    </div>
                                ) : null}
                            </div>
                        ) : (
                            <div className="text-[var(--red)] font-mono text-sm">
                                ✗ Falló — revisá los datos.
                                <pre className="codeblock mt-2 text-[10px]">
                                    {JSON.stringify(testResult, null, 2)}
                                </pre>
                            </div>
                        )}
                    </div>
                ) : null}
            </div>
        </div>
    );
}

function Field({ label, required, hint, children }) {
    return (
        <div>
            <label className="kicker text-[var(--text-faint)] mb-1 block">
                {label} {required ? <span className="text-[var(--red)]">*</span> : null}
            </label>
            {children}
            {hint ? (
                <div className="text-[10px] text-[var(--text-faint)] font-mono mt-1">
                    {hint}
                </div>
            ) : null}
        </div>
    );
}

// =============================================================================
// ADVANCED TAB — env vars editables, capital reset, deposits
// =============================================================================
function AdvancedTab() {
    const [config, setConfig] = useState(null);
    const [form, setForm] = useState(null);
    const [saving, setSaving] = useState(false);

    const fetchConfig = useCallback(() => {
        apiGet("/bot/config")
            .then((r) => {
                setConfig(r.data);
                // Solo hidrata el form si todavía no fue editado o si fue
                // recién guardado (form === null). Esto evita pisar input
                // del usuario en re-fetches automáticos.
                setForm((prev) => prev ?? {
                    TRADING_MODE: r.data?.TRADING_MODE || "demo",
                    MAX_LOTS_PER_TRADE: r.data?.MAX_LOTS_PER_TRADE ?? "0.5",
                    MT5_MAGIC: r.data?.MT5_MAGIC ?? "",
                    SYNC_INTERVAL_SECONDS: r.data?.SYNC_INTERVAL_SECONDS ?? "30",
                });
            })
            .catch((e) => console.error(e));
    }, []);

    useEffect(() => {
        fetchConfig();
        // Listener: cuando otra parte de la app cambia /bot/config, re-hidratamos.
        const onChanged = () => {
            setForm(null);     // marca como "no dirty" → el siguiente fetchConfig hidrata
            fetchConfig();
        };
        window.addEventListener("botconfig:changed", onChanged);
        return () => window.removeEventListener("botconfig:changed", onChanged);
    }, [fetchConfig]);

    const save = async () => {
        if (!form) return;
        setSaving(true);
        try {
            const r = await apiPost("/bot/config", { updates: form });
            if (r.data?.ok) {
                toast.success("Configuración guardada. Reiniciá el bot para aplicar.");
                // Re-fetch propio para reflejar lo que el backend efectivamente guardó
                // (puede haber normalización de paths, etc).
                setForm(null);
                fetchConfig();
                window.dispatchEvent(new CustomEvent("botconfig:changed"));
            } else {
                toast.error("No se pudo guardar");
            }
        } catch (e) {
            toast.error(`Error: ${e.message}`);
        } finally {
            setSaving(false);
        }
    };

    if (!form) {
        return <div className="panel p-5 text-xs font-mono">Cargando…</div>;
    }

    return (
        <div className="space-y-4">
            <div className="panel p-6">
                <div className="kicker mb-3">CONFIGURACIÓN DEL BOT (.env)</div>
                <p className="text-xs text-[var(--text-dim)] mb-4">
                    Variables de entorno editables. Después de guardar, reiniciá el
                    bot desde Procesos para que las tome.
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
                    <Field label="Modo" hint="demo / paper / live">
                        <select
                            className="input-sharp"
                            value={form.TRADING_MODE}
                            onChange={(e) => setForm({ ...form, TRADING_MODE: e.target.value })}
                        >
                            <option value="demo">demo</option>
                            <option value="paper">paper</option>
                            <option value="live">live</option>
                        </select>
                    </Field>
                    <Field label="Max lots por trade" hint="cap absoluto">
                        <input
                            className="input-sharp"
                            type="number"
                            step="0.01"
                            value={form.MAX_LOTS_PER_TRADE}
                            onChange={(e) =>
                                setForm({ ...form, MAX_LOTS_PER_TRADE: e.target.value })
                            }
                        />
                    </Field>
                    <Field label="Magic ID" hint="identifica trades del bot">
                        <input
                            className="input-sharp"
                            type="number"
                            value={form.MT5_MAGIC}
                            onChange={(e) =>
                                setForm({ ...form, MT5_MAGIC: e.target.value })
                            }
                        />
                    </Field>
                    <Field label="Sync interval (s)" hint="entre 10 y 600">
                        <input
                            className="input-sharp"
                            type="number"
                            min="10"
                            max="600"
                            value={form.SYNC_INTERVAL_SECONDS}
                            onChange={(e) =>
                                setForm({ ...form, SYNC_INTERVAL_SECONDS: e.target.value })
                            }
                        />
                    </Field>
                </div>
                <button
                    type="button"
                    onClick={save}
                    disabled={saving}
                    className="btn-sharp primary flex items-center gap-2"
                >
                    <Save size={12} />
                    {saving ? "Guardando…" : "Guardar"}
                </button>
            </div>
        </div>
    );
}
