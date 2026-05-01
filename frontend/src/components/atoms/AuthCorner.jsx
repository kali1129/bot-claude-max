// AuthCorner — pill superior-derecha que muestra el estado de auth.
//
// 3 modos:
//   - Anónimo: botón "Iniciar sesión" + link "Crear cuenta".
//   - Logged user (no admin): pill con email + botón Salir.
//   - Logged admin: pill con email + badge ADMIN + botón Salir.
//
// Click en el pill abre dropdown con opciones rápidas.

import { useState, useRef, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LogIn, LogOut, User, Shield, ChevronDown } from "lucide-react";
import { useAuth } from "@/lib/AuthProvider";

export default function AuthCorner() {
    const { user, isAdmin, isAuthenticated, logout } = useAuth();
    const navigate = useNavigate();
    const [open, setOpen] = useState(false);
    const ref = useRef(null);

    useEffect(() => {
        const onDoc = (e) => {
            if (!ref.current || !ref.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, []);

    if (!isAuthenticated) {
        return (
            <Link
                to="/login"
                className="btn-sharp flex items-center gap-2"
                data-testid="auth-login-link"
                title="Iniciar sesión"
            >
                <LogIn size={12} />
                <span className="hidden sm:inline">Entrar</span>
            </Link>
        );
    }

    const label = user?.display_name || user?.email || "Usuario";

    return (
        <div className="relative" ref={ref}>
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className={`btn-sharp flex items-center gap-2 ${isAdmin ? "primary" : ""}`}
                data-testid="auth-user-pill"
                title={user?.email}
            >
                {isAdmin ? <Shield size={12} /> : <User size={12} />}
                <span className="hidden sm:inline truncate max-w-[120px]">
                    {label}
                </span>
                <ChevronDown size={11} />
            </button>
            {open ? (
                <div
                    className="absolute right-0 mt-1 w-52 z-50 panel"
                    role="menu"
                    style={{ background: "var(--surface-2)" }}
                >
                    <div className="px-3 py-2.5 border-b border-[var(--border)]">
                        <div className="kicker mb-0.5">
                            {isAdmin ? "ADMIN" : "USUARIO"}
                        </div>
                        <div className="font-mono text-xs truncate">
                            {user?.email}
                        </div>
                    </div>
                    {!isAdmin ? (
                        <div className="px-3 py-2 text-[10px] text-[var(--text-faint)] border-b border-[var(--border)]">
                            Modo demo. Pronto vas a poder conectar tu propia cuenta.
                        </div>
                    ) : null}
                    <button
                        type="button"
                        onClick={() => {
                            setOpen(false);
                            logout();
                        }}
                        className="w-full text-left px-3 py-2.5 text-xs font-mono hover:bg-[var(--surface)] flex items-center gap-2 text-[var(--red)]"
                    >
                        <LogOut size={11} />
                        Cerrar sesión
                    </button>
                </div>
            ) : null}
        </div>
    );
}
