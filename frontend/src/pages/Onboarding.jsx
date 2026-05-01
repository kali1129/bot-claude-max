// Onboarding wizard — 6 steps + step 7 (success).
// Layout: card central 560px, breadcrumb arriba, footer Atrás/Saltar/Siguiente.
// Persistencia: localStorage (`onboarding_progress_v1`) por si recarga.

import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check, GraduationCap, Wrench } from "lucide-react";
import { toast } from "sonner";

import { useSettings } from "@/lib/userMode";
import { apiPost } from "@/lib/api";

import StylePresetCard from "@/components/atoms/StylePresetCard";
import SessionSelector from "@/components/atoms/SessionSelector";
import TelegramChatInput from "@/components/atoms/TelegramChatInput";
import WarningModal from "@/components/atoms/WarningModal";
import ReferralBanner from "@/components/atoms/ReferralBanner";

const TOTAL_STEPS = 6;
const STORAGE_KEY = "onboarding_progress_v1";

const DEFAULT_DRAFT = {
    step: 1,
    mode: "novato",
    goal_usd: 1500,
    style: "balanceado",
    sessions: ["24/7"],
};

function loadDraft() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return { ...DEFAULT_DRAFT };
        return { ...DEFAULT_DRAFT, ...JSON.parse(raw) };
    } catch {
        return { ...DEFAULT_DRAFT };
    }
}

function saveDraft(draft) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
    } catch {}
}

function clearDraft() {
    try {
        localStorage.removeItem(STORAGE_KEY);
    } catch {}
}

export default function Onboarding() {
    const navigate = useNavigate();
    const { settings, updateSettings, completeOnboarding } = useSettings();

    const [draft, setDraft] = useState(loadDraft);
    const [warnAggressive, setWarnAggressive] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [success, setSuccess] = useState(false);

    useEffect(() => {
        saveDraft(draft);
    }, [draft]);

    // Si el usuario ya tiene settings cargado al backend (pero onboarded=false),
    // hidratamos el draft con esos valores la primera vez.
    useEffect(() => {
        if (!settings) return;
        setDraft((d) => ({
            ...d,
            mode: d.mode || settings.mode || "novato",
            goal_usd: d.goal_usd ?? settings.goal_usd ?? 1500,
            style: d.style || settings.style || "balanceado",
            sessions:
                d.sessions && d.sessions.length
                    ? d.sessions
                    : settings.sessions || ["24/7"],
        }));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [settings?.mode, settings?.goal_usd, settings?.style]);

    const stepNum = draft.step;
    const update = (patch) => setDraft((d) => ({ ...d, ...patch }));

    const next = () => {
        if (stepNum < TOTAL_STEPS) update({ step: stepNum + 1 });
    };
    const back = () => {
        if (stepNum > 1) update({ step: stepNum - 1 });
    };

    const handleStyleChoice = (key) => {
        if (key === "agresivo") {
            setWarnAggressive(true);
            return;
        }
        update({ style: key });
    };

    const confirmAggressive = () => {
        update({ style: "agresivo" });
        setWarnAggressive(false);
    };

    const finalize = async () => {
        setSubmitting(true);
        try {
            await updateSettings({
                mode: draft.mode,
                goal_usd: Number(draft.goal_usd),
                style: draft.style,
                sessions: draft.sessions,
            });
            await apiPost("/settings/onboarding/complete");
            await completeOnboarding();
            clearDraft();
            setSuccess(true);
            // Pequeño delay y redirige
            setTimeout(() => {
                navigate("/", { replace: true });
            }, 1500);
        } catch (e) {
            console.error("onboarding finalize error", e);
            toast.error("No se pudo guardar tu configuración. Intentá de nuevo.");
        } finally {
            setSubmitting(false);
        }
    };

    const styles = useMemo(
        () => settings?.available_styles || {
            conservativo: { risk_pct: 0.5, max_pos: 1, min_rr: 2.0 },
            balanceado: { risk_pct: 1.0, max_pos: 3, min_rr: 2.0 },
            agresivo: { risk_pct: 2.0, max_pos: 5, min_rr: 1.8 },
        },
        [settings?.available_styles]
    );

    if (success) {
        return <SuccessScreen />;
    }

    return (
        <div
            className="min-h-screen grid-bg flex items-center justify-center px-4 py-10"
            data-testid="onboarding"
        >
            <div className="w-full max-w-[560px]">
                <Breadcrumb step={stepNum} total={TOTAL_STEPS} />

                <div className="panel p-6 md:p-8">
                    {stepNum === 1 && (
                        <Step1
                            mode={draft.mode}
                            onPick={(m) => {
                                update({ mode: m });
                                next();
                            }}
                        />
                    )}
                    {stepNum === 2 && (
                        <Step2
                            value={draft.goal_usd}
                            onChange={(v) => update({ goal_usd: v })}
                        />
                    )}
                    {stepNum === 3 && (
                        <Step3
                            value={draft.style}
                            styles={styles}
                            onChoice={handleStyleChoice}
                        />
                    )}
                    {stepNum === 4 && (
                        <Step4
                            value={draft.sessions}
                            onChange={(s) => update({ sessions: s })}
                        />
                    )}
                    {stepNum === 5 && <Step5 />}
                    {stepNum === 6 && (
                        <Step6
                            chats={settings?.telegram_chat_ids || []}
                            refresh={() => {}}
                        />
                    )}

                    {/* Footer */}
                    <Footer
                        stepNum={stepNum}
                        total={TOTAL_STEPS}
                        onBack={back}
                        onNext={next}
                        onSkip={next}
                        onFinalize={finalize}
                        canNext={canAdvance(stepNum, draft)}
                        showSkipFor={[5, 6].includes(stepNum)}
                        submitting={submitting}
                    />
                </div>
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
                                <span className="text-[var(--red)]">
                                    (4× más que conservativo)
                                </span>
                            </li>
                            <li>Abrir hasta 5 operaciones a la vez</li>
                            <li>Buscar entradas con menos confirmación</li>
                        </ul>
                        <p className="font-semibold mt-3">¿Qué significa esto?</p>
                        <ul className="list-disc list-inside space-y-1 text-[var(--text-dim)]">
                            <li>
                                Podés tener rachas de pérdidas más fuertes (-15% a -25%
                                de la cuenta no es raro)
                            </li>
                            <li>Si el bot tiene un día malo, recuperarte tarda más</li>
                            <li>
                                NO es mejor. Es solo más rápido cuando funciona y más
                                doloroso cuando no.
                            </li>
                        </ul>
                    </div>
                }
                checkboxText="Entiendo el riesgo y acepto la responsabilidad. No es plata que necesite."
                cancelLabel="Cancelar, mejor balanceado"
                confirmLabel="Confirmar agresivo"
                danger
                onCancel={() => update({ style: "balanceado" })}
                onConfirm={confirmAggressive}
            />
        </div>
    );
}

function canAdvance(step, draft) {
    if (step === 1) return !!draft.mode;
    if (step === 2) {
        const n = Number(draft.goal_usd);
        return Number.isFinite(n) && n >= 100 && n <= 1_000_000;
    }
    if (step === 3) return !!draft.style;
    if (step === 4) return Array.isArray(draft.sessions) && draft.sessions.length > 0;
    if (step === 5) return true;
    if (step === 6) return true;
    return true;
}

// -----------------------------------------------------------------------------
// Footer
// -----------------------------------------------------------------------------
function Footer({
    stepNum,
    total,
    onBack,
    onNext,
    onSkip,
    onFinalize,
    canNext,
    showSkipFor = false,
    submitting = false,
}) {
    const isLast = stepNum === total;
    const hideBack = stepNum === 1;
    return (
        <div className="mt-8 pt-5 border-t border-[var(--border)] flex items-center justify-between gap-2 flex-wrap">
            {!hideBack ? (
                <button
                    type="button"
                    onClick={onBack}
                    className="btn-sharp flex items-center gap-2"
                    data-testid="onboarding-back"
                >
                    <ArrowLeft size={12} /> Atrás
                </button>
            ) : (
                <span />
            )}

            <div className="flex items-center gap-2">
                {showSkipFor ? (
                    <button
                        type="button"
                        onClick={onSkip}
                        className="text-xs font-mono text-[var(--text-dim)] underline"
                        data-testid="onboarding-skip"
                    >
                        Saltar, configurar después
                    </button>
                ) : null}
                {isLast ? (
                    <button
                        type="button"
                        onClick={onFinalize}
                        disabled={!canNext || submitting}
                        className="btn-sharp primary flex items-center gap-2"
                        data-testid="onboarding-finalize"
                    >
                        {submitting ? "Guardando…" : "Terminar"} <Check size={12} />
                    </button>
                ) : stepNum === 1 ? null : (
                    <button
                        type="button"
                        onClick={onNext}
                        disabled={!canNext}
                        className="btn-sharp primary flex items-center gap-2"
                        data-testid="onboarding-next"
                    >
                        Siguiente <ArrowRight size={12} />
                    </button>
                )}
            </div>
        </div>
    );
}

// -----------------------------------------------------------------------------
// Breadcrumb
// -----------------------------------------------------------------------------
function Breadcrumb({ step, total }) {
    return (
        <div className="flex items-center gap-2 mb-5 justify-center" data-testid="onboarding-breadcrumb">
            {Array.from({ length: total }).map((_, i) => {
                const n = i + 1;
                const active = n === step;
                const done = n < step;
                return (
                    <div key={n} className="flex items-center gap-2">
                        <div
                            className={`flex items-center justify-center w-7 h-7 text-xs font-mono font-bold border ${
                                active
                                    ? "border-[var(--green)] bg-[var(--green)] text-black"
                                    : done
                                    ? "border-[var(--green)] text-[var(--green)]"
                                    : "border-[var(--border)] text-[var(--text-faint)]"
                            }`}
                        >
                            {done ? <Check size={12} /> : n}
                        </div>
                        {n < total && (
                            <div
                                className="w-5 h-px"
                                style={{
                                    background: done
                                        ? "var(--green)"
                                        : "var(--border)",
                                }}
                            />
                        )}
                    </div>
                );
            })}
        </div>
    );
}

// -----------------------------------------------------------------------------
// Steps
// -----------------------------------------------------------------------------
function Step1({ mode, onPick }) {
    return (
        <div data-testid="step-1">
            <div className="kicker mb-2">PASO 1 / 6</div>
            <h1 className="font-display text-3xl font-black mb-3">
                Hola 👋 Vamos a configurar tu bot
            </h1>
            <p className="text-sm text-[var(--text-dim)] mb-6 leading-relaxed">
                En 2 minutos vas a tener todo listo. Te voy a hacer 5 preguntas
                simples. Si algo no entendés, hay ayuda en cada paso.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <button
                    type="button"
                    onClick={() => onPick("novato")}
                    className={`p-5 border-2 text-left transition-colors ${
                        mode === "novato"
                            ? "border-[var(--novato-accent)] bg-[var(--novato-bg)]"
                            : "border-[var(--border)] hover:border-[var(--border-strong)]"
                    }`}
                    data-testid="pick-novato"
                >
                    <GraduationCap size={28} className="mb-2 text-[var(--novato-accent)]" />
                    <div className="font-display text-lg font-bold mb-1">
                        Soy nuevo en trading
                    </div>
                    <div className="text-xs text-[var(--text-dim)]">
                        Te muestro lo simple. Tooltips en cada término. Recomendaciones
                        seguras por defecto.
                    </div>
                </button>
                <button
                    type="button"
                    onClick={() => onPick("experto")}
                    className={`p-5 border-2 text-left transition-colors ${
                        mode === "experto"
                            ? "border-[var(--green)] bg-[var(--success-soft)]"
                            : "border-[var(--border)] hover:border-[var(--border-strong)]"
                    }`}
                    data-testid="pick-experto"
                >
                    <Wrench size={28} className="mb-2 text-[var(--green-bright)]" />
                    <div className="font-display text-lg font-bold mb-1">
                        Tengo experiencia
                    </div>
                    <div className="text-xs text-[var(--text-dim)]">
                        Acceso completo. Métricas pro, params crudos, backtesting,
                        optimizer. Sin tooltips.
                    </div>
                </button>
            </div>
        </div>
    );
}

function Step2({ value, onChange }) {
    const num = Number(value);
    const valid = Number.isFinite(num) && num >= 100 && num <= 1_000_000;
    return (
        <div data-testid="step-2">
            <div className="kicker mb-2">PASO 2 / 6</div>
            <h2 className="font-display text-3xl font-black mb-3">
                ¿Cuál es tu meta?
            </h2>
            <p className="text-sm text-[var(--text-dim)] mb-5">
                Ponele un número realista. El bot va a ajustar el tamaño de cada
                operación para llegar ahí sin volar la cuenta.
            </p>

            <label className="kicker mb-1 block">Meta en USD</label>
            <div className="flex items-center gap-2 mb-2">
                <span className="font-mono text-2xl text-[var(--text-faint)]">$</span>
                <input
                    type="number"
                    min={100}
                    max={1_000_000}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    placeholder="ej. 1500"
                    className="input-sharp text-lg font-mono tabular flex-1"
                    data-testid="goal-input"
                />
            </div>
            {!valid && Number(value) > 0 ? (
                <div className="text-xs text-[var(--red)] mb-3">
                    El valor tiene que estar entre $100 y $1,000,000.
                </div>
            ) : null}

            <div className="flex flex-wrap gap-2 mt-3">
                {[500, 1500, 5000, 10000].map((preset) => (
                    <button
                        key={preset}
                        type="button"
                        onClick={() => onChange(preset)}
                        data-testid={`goal-quick-${preset}`}
                        className={`btn-sharp ${
                            Number(value) === preset ? "primary" : ""
                        }`}
                    >
                        ${preset.toLocaleString()}
                    </button>
                ))}
            </div>

            <div className="kicker mt-5 normal-case tracking-normal text-[var(--text-dim)]">
                No tenés que poner todo de golpe. Empezamos con lo que tengas y
                vamos sumando.
            </div>
        </div>
    );
}

function Step3({ value, styles, onChoice }) {
    return (
        <div data-testid="step-3">
            <div className="kicker mb-2">PASO 3 / 6</div>
            <h2 className="font-display text-3xl font-black mb-3">
                ¿Qué tipo de bot preferís?
            </h2>
            <p className="text-sm text-[var(--text-dim)] mb-5">
                Esto define cuánto riesgo toma por cada operación. Podés cambiarlo
                cuando quieras.
            </p>

            <div className="space-y-3">
                <StylePresetCard
                    presetKey="conservativo"
                    preset={styles.conservativo || {}}
                    active={value === "conservativo"}
                    onClick={() => onChoice("conservativo")}
                />
                <StylePresetCard
                    presetKey="balanceado"
                    preset={styles.balanceado || {}}
                    active={value === "balanceado"}
                    recommended
                    onClick={() => onChoice("balanceado")}
                />
                <StylePresetCard
                    presetKey="agresivo"
                    preset={styles.agresivo || {}}
                    active={value === "agresivo"}
                    onClick={() => onChoice("agresivo")}
                />
            </div>
        </div>
    );
}

function Step4({ value, onChange }) {
    return (
        <div data-testid="step-4">
            <div className="kicker mb-2">PASO 4 / 6</div>
            <h2 className="font-display text-3xl font-black mb-3">
                ¿Cuándo querés que opere?
            </h2>
            <p className="text-sm text-[var(--text-dim)] mb-5">
                El mercado tiene horarios. Podés dejarlo 24/7 o limitar a las
                sesiones más activas.
            </p>

            <SessionSelector value={value} onChange={onChange} />

            <div className="kicker mt-5 normal-case tracking-normal text-[var(--text-dim)]">
                Si elegís varias sesiones, el bot opera durante todas. Si dudás,
                dejá 24/7 — el bot ya filtra los momentos malos por su cuenta.
            </div>
        </div>
    );
}

function Step5() {
    return (
        <div data-testid="step-5">
            <div className="kicker mb-2">PASO 5 / 6</div>
            <h2 className="font-display text-3xl font-black mb-3">
                Conectá tu cuenta de trading
            </h2>
            <p className="text-sm text-[var(--text-dim)] mb-5">
                El bot necesita una cuenta de broker para operar. Si no tenés, te
                recomendamos XM (es gratis y está integrado con este sistema).
            </p>

            <ReferralBanner variant="feature" />

            <div className="mt-5 panel p-4">
                <div className="kicker mb-2">CONECTAR DESPUÉS</div>
                <p className="text-xs text-[var(--text-dim)]">
                    Vas a poder ingresar los datos de tu MT5 (login, password,
                    server, path) en{" "}
                    <span className="text-[var(--green-bright)]">
                        Configuración → MT5
                    </span>
                    . Hay un botón "Probar conexión" que te avisa si todo está OK
                    antes de guardar.
                </p>
                <p className="text-xs text-[var(--text-faint)] mt-2">
                    Tu password se guarda solo en tu computadora, en un archivo
                    encriptado. No la enviamos a ningún lado.
                </p>
            </div>
        </div>
    );
}

function Step6({ chats, refresh }) {
    return (
        <div data-testid="step-6">
            <div className="kicker mb-2">PASO 6 / 6</div>
            <h2 className="font-display text-3xl font-black mb-3">
                ¿Querés notificaciones en Telegram?
            </h2>
            <p className="text-sm text-[var(--text-dim)] mb-5">
                Te avisamos cuando el bot abre o cierra una operación, o si pasa
                algo importante. Es opcional.
            </p>

            <TelegramChatInput chats={chats} onChange={refresh} />
        </div>
    );
}

// -----------------------------------------------------------------------------
// SuccessScreen
// -----------------------------------------------------------------------------
function SuccessScreen() {
    return (
        <div
            className="min-h-screen grid-bg flex items-center justify-center px-4"
            data-testid="onboarding-success"
        >
            <div className="panel p-8 max-w-md text-center">
                <div className="text-5xl mb-3">🎉</div>
                <h1 className="font-display text-3xl font-black mb-2">
                    Todo listo
                </h1>
                <p className="text-sm text-[var(--text-dim)] mb-5">
                    Tu bot está configurado. Te llevamos al tablero — desde ahí
                    podés encenderlo cuando quieras.
                </p>
                <div className="text-xs font-mono text-[var(--text-faint)]">
                    Redirigiendo…
                </div>
            </div>
        </div>
    );
}
