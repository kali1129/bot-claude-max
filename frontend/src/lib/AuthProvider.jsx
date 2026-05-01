// AuthProvider — context React que expone el estado de autenticación.
//
// Hooks:
//   useAuth() → { user, isAdmin, isAuthenticated, login, register, logout, refresh }
//
// Listener de 'auth:expired' (disparado por api.js cuando un endpoint
// devuelve 401): limpia sesión y notifica al provider.

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { apiPost, apiGet } from "./api";
import {
    getToken, getUser, setSession, clearSession,
    isExpired,
} from "./auth";

const AuthContext = createContext({
    user: null,
    isAuthenticated: false,
    isAdmin: false,
    loading: true,
    login: async () => {},
    register: async () => {},
    logout: () => {},
    refresh: async () => {},
});

export function AuthProvider({ children }) {
    const [user, setUser] = useState(getUser());
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();

    const refresh = useCallback(async () => {
        const t = getToken();
        if (!t || isExpired(t)) {
            clearSession();
            setUser(null);
            setLoading(false);
            return null;
        }
        try {
            const r = await apiGet("/auth/me");
            setUser(r.data);
            try {
                localStorage.setItem("bot_user", JSON.stringify(r.data));
            } catch {
                // noop
            }
            return r.data;
        } catch (e) {
            // 401 → interceptor ya borró la sesión
            setUser(null);
            return null;
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        refresh();
        const onExpired = () => {
            setUser(null);
            toast.error("Tu sesión expiró. Hacé login de nuevo.");
            navigate("/login", { replace: true });
        };
        window.addEventListener("auth:expired", onExpired);
        return () => window.removeEventListener("auth:expired", onExpired);
    }, [refresh, navigate]);

    const login = useCallback(async (email, password) => {
        const r = await apiPost("/auth/login", { email, password });
        const token = r.data?.token;
        const u = r.data?.user;
        if (!token || !u) throw new Error("respuesta inválida del server");
        setSession(token, u);
        setUser(u);
        return u;
    }, []);

    const register = useCallback(async (email, password, displayName) => {
        const r = await apiPost("/auth/register", {
            email,
            password,
            display_name: displayName || null,
        });
        const token = r.data?.token;
        const u = r.data?.user;
        if (!token || !u) throw new Error("respuesta inválida del server");
        setSession(token, u);
        setUser(u);
        return u;
    }, []);

    const logout = useCallback(() => {
        clearSession();
        setUser(null);
        toast.success("Sesión cerrada");
        navigate("/login", { replace: true });
    }, [navigate]);

    const value = {
        user,
        isAuthenticated: !!user,
        isAdmin: !!user && user.role === "admin",
        loading,
        login,
        register,
        logout,
        refresh,
    };

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
    return useContext(AuthContext);
}

// Wrapper para rutas que requieren admin (Fase 1: TODA la admin UI).
// Si el usuario no es admin, muestra un mensaje friendly + CTA login.
export function RequireAdmin({ children, fallback }) {
    const { isAdmin, loading, user } = useAuth();
    if (loading) return null;
    if (!isAdmin) return fallback || <NotAdmin user={user} />;
    return children;
}

function NotAdmin({ user }) {
    const navigate = useNavigate();
    return (
        <div className="min-h-[60vh] flex items-center justify-center px-6">
            <div className="panel p-8 max-w-md text-center" data-testid="not-admin-block">
                <div className="kicker mb-3">// ACCESO RESTRINGIDO</div>
                <h2 className="font-display text-2xl font-black mb-3">
                    Esta sección es solo para el dueño del bot
                </h2>
                <p className="text-sm text-[var(--text-dim)] mb-5">
                    {user
                        ? "Tu cuenta no tiene permisos de admin. La Fase 2 va a permitir que cada usuario tenga su propio bot — pronto."
                        : "Iniciá sesión con la cuenta admin para acceder."}
                </p>
                {!user ? (
                    <button
                        onClick={() => navigate("/login")}
                        className="btn-sharp primary"
                    >
                        Iniciar sesión
                    </button>
                ) : null}
            </div>
        </div>
    );
}
