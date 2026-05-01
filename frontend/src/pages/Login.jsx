// Login — página de inicio de sesión.
// Si el usuario ya está autenticado, redirige a / (Home).

import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { LogIn, Loader2, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/AuthProvider";

export default function Login() {
    const { login, isAuthenticated, loading } = useAuth();
    const navigate = useNavigate();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [showPwd, setShowPwd] = useState(false);
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        if (!loading && isAuthenticated) {
            navigate("/", { replace: true });
        }
    }, [loading, isAuthenticated, navigate]);

    const submit = async (e) => {
        e.preventDefault();
        if (!email || !password) {
            toast.error("Email y contraseña son obligatorios");
            return;
        }
        setBusy(true);
        try {
            const u = await login(email, password);
            toast.success(`Bienvenido${u.display_name ? ", " + u.display_name : ""}`);
            navigate("/", { replace: true });
        } catch (e) {
            const msg = e.response?.data?.detail || "Email o contraseña incorrectos";
            toast.error(msg);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div
            className="min-h-screen flex items-center justify-center px-4 py-10"
            data-testid="page-login"
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
                            Iniciar sesión
                        </h2>
                        <p className="text-xs text-[var(--text-dim)]">
                            Si todavía no tenés cuenta,{" "}
                            <Link
                                to="/register"
                                className="text-[var(--green-bright)] underline"
                            >
                                creá una acá
                            </Link>
                            .
                        </p>
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
                            data-testid="login-email"
                        />
                    </div>

                    <div>
                        <label
                            className="kicker block mb-2"
                            htmlFor="password"
                        >
                            CONTRASEÑA
                        </label>
                        <div className="relative">
                            <input
                                id="password"
                                type={showPwd ? "text" : "password"}
                                autoComplete="current-password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                className="input-sharp w-full pr-10"
                                placeholder="••••••••"
                                disabled={busy}
                                required
                                data-testid="login-password"
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
                    </div>

                    <button
                        type="submit"
                        disabled={busy}
                        className="btn-sharp primary btn-xl w-full flex items-center justify-center gap-2"
                        data-testid="login-submit"
                    >
                        {busy ? (
                            <Loader2 size={14} className="animate-spin" />
                        ) : (
                            <LogIn size={14} />
                        )}
                        {busy ? "Entrando..." : "Entrar"}
                    </button>
                </form>

                <div className="text-center mt-4 text-xs text-[var(--text-faint)]">
                    También podés{" "}
                    <Link to="/" className="underline">
                        ver la demo pública
                    </Link>{" "}
                    sin cuenta.
                </div>
            </div>
        </div>
    );
}
