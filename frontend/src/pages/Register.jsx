// Register — página para crear cuenta nueva (role=user).
//
// FASE 1: estos usuarios pueden ver el dashboard pero NO modificar el
// bot — el bot opera con la cuenta MT5 del admin. En FASE 2 cada user
// va a poder conectar SU MT5.
//
// Incluye link prominente a XM Global (afiliado).

import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { UserPlus, Loader2, Eye, EyeOff, ExternalLink } from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/AuthProvider";

const XM_REFERRAL = "https://www.xmglobal.com/referral?token=OtZfgkRKCdH25RlT1gJ7hQ";

export default function Register() {
    const { register, isAuthenticated, loading } = useAuth();
    const navigate = useNavigate();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [displayName, setDisplayName] = useState("");
    const [showPwd, setShowPwd] = useState(false);
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        if (!loading && isAuthenticated) {
            navigate("/", { replace: true });
        }
    }, [loading, isAuthenticated, navigate]);

    const valid =
        email && /\S+@\S+\.\S+/.test(email) && password.length >= 8;

    const submit = async (e) => {
        e.preventDefault();
        if (!valid) {
            toast.error("Email válido y contraseña ≥ 8 caracteres");
            return;
        }
        setBusy(true);
        try {
            const u = await register(email, password, displayName.trim() || null);
            toast.success(`Cuenta creada · bienvenido ${u.display_name || u.email}`);
            navigate("/", { replace: true });
        } catch (e) {
            const msg = e.response?.data?.detail || "No se pudo crear la cuenta";
            toast.error(msg);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div
            className="min-h-screen flex items-center justify-center px-4 py-10"
            data-testid="page-register"
        >
            <div className="w-full max-w-md">
                <div className="text-center mb-6">
                    <div className="font-display text-4xl font-black tracking-tight">
                        OPS<span className="text-[var(--green)]">.</span>
                    </div>
                    <div className="kicker mt-1 text-[var(--text-dim)]">
                        TRADING AUTOMÁTICO
                    </div>
                </div>

                <form
                    onSubmit={submit}
                    className="panel p-6 space-y-4"
                    autoComplete="on"
                >
                    <div>
                        <h2 className="font-display text-2xl font-bold mb-1">
                            Crear cuenta
                        </h2>
                        <p className="text-xs text-[var(--text-dim)]">
                            ¿Ya tenés cuenta?{" "}
                            <Link
                                to="/login"
                                className="text-[var(--green-bright)] underline"
                            >
                                Iniciar sesión
                            </Link>
                            .
                        </p>
                    </div>

                    {/* Aviso de qué van a poder hacer */}
                    <div
                        className="border-l-2 px-3 py-2.5 text-[11px] leading-relaxed"
                        style={{
                            borderColor: "var(--blue)",
                            background: "rgba(59,130,246,0.05)",
                        }}
                    >
                        <div className="font-mono font-bold text-[var(--blue)] mb-1">
                            QUÉ PODÉS HACER CON ESTA CUENTA
                        </div>
                        <ul className="space-y-1 text-[var(--text-dim)] list-disc list-inside">
                            <li>
                                Ver el bot del admin operando en vivo (
                                <strong className="text-white">read-only</strong>).
                            </li>
                            <li>
                                Guardar tu mode novato/experto y preferencias visuales.
                            </li>
                            <li>
                                <strong className="text-[var(--text-faint)]">
                                    Pronto:
                                </strong>{" "}
                                conectar tu MT5 y que el bot opere con tu propia cuenta XM.
                            </li>
                        </ul>
                        <div className="mt-2 text-[var(--text-faint)]">
                            Tu cuenta NO afecta la cuenta del admin. El bot global
                            sigue siendo del proyecto, solo el admin puede modificarlo.
                        </div>
                    </div>

                    <div>
                        <label
                            className="kicker block mb-2"
                            htmlFor="display-name"
                        >
                            ¿CÓMO TE LLAMÁS? (OPCIONAL)
                        </label>
                        <input
                            id="display-name"
                            type="text"
                            autoComplete="name"
                            value={displayName}
                            onChange={(e) => setDisplayName(e.target.value)}
                            className="input-sharp w-full"
                            placeholder="Pedro"
                            disabled={busy}
                            maxLength={64}
                            data-testid="register-name"
                        />
                    </div>

                    <div>
                        <label
                            className="kicker block mb-2"
                            htmlFor="email"
                        >
                            EMAIL
                        </label>
                        <input
                            id="email"
                            type="email"
                            autoComplete="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            className="input-sharp w-full"
                            placeholder="tu@correo.com"
                            disabled={busy}
                            required
                            data-testid="register-email"
                        />
                    </div>

                    <div>
                        <label
                            className="kicker block mb-2"
                            htmlFor="password"
                        >
                            CONTRASEÑA (MIN. 8)
                        </label>
                        <div className="relative">
                            <input
                                id="password"
                                type={showPwd ? "text" : "password"}
                                autoComplete="new-password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                className="input-sharp w-full pr-10"
                                placeholder="••••••••"
                                disabled={busy}
                                required
                                minLength={8}
                                data-testid="register-password"
                            />
                            <button
                                type="button"
                                onClick={() => setShowPwd((v) => !v)}
                                className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-faint)] hover:text-white"
                                aria-label={showPwd ? "Ocultar" : "Mostrar"}
                                tabIndex={-1}
                            >
                                {showPwd ? <EyeOff size={14} /> : <Eye size={14} />}
                            </button>
                        </div>
                        {password.length > 0 && password.length < 8 ? (
                            <div className="text-xs text-[var(--red)] mt-1">
                                Faltan {8 - password.length} caracteres
                            </div>
                        ) : null}
                    </div>

                    <button
                        type="submit"
                        disabled={busy || !valid}
                        className="btn-sharp primary btn-xl w-full flex items-center justify-center gap-2"
                        data-testid="register-submit"
                    >
                        {busy ? (
                            <Loader2 size={14} className="animate-spin" />
                        ) : (
                            <UserPlus size={14} />
                        )}
                        {busy ? "Creando..." : "Crear cuenta"}
                    </button>

                    <div className="text-[10px] text-[var(--text-faint)] text-center pt-1">
                        Al registrarte aceptás que esto es <strong>modo demo</strong>.
                        Pronto vas a poder conectar tu propia cuenta MT5.
                    </div>
                </form>

                {/* Banner XM afiliados */}
                <div
                    className="mt-6 panel p-5 border-[var(--green)]"
                    style={{ background: "rgba(16, 185, 129, 0.05)" }}
                >
                    <div className="kicker text-[var(--green-bright)] mb-2">
                        // PRÓXIMO PASO
                    </div>
                    <div className="font-display text-lg font-bold mb-2">
                        ¿Querés operar de verdad?
                    </div>
                    <p className="text-xs text-[var(--text-dim)] mb-3 leading-relaxed">
                        El bot opera sobre cuentas <strong>XM Global</strong>.
                        Creá tu cuenta acá (es gratis) y empezás con demo de
                        $100,000 USD virtuales.
                    </p>
                    <a
                        href={XM_REFERRAL}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="btn-sharp success btn-xl w-full flex items-center justify-center gap-2"
                    >
                        <ExternalLink size={14} />
                        Crear cuenta en XM Global
                    </a>
                </div>
            </div>
        </div>
    );
}
