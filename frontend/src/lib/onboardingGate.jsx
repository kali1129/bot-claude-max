// OnboardingGate
//
// Si `settings.onboarded === false` y la ruta actual no está en la whitelist
// (`/onboarding` y `/ayuda`), redirige a `/onboarding` para forzar el wizard.
//
// Aplicar en App.js para todas las rutas excepto las whitelist.
//
// FASE 1 multi-tenant: el onboarding wizard ahora es ADMIN-ONLY (porque
// configura el bot del admin). Los usuarios comunes (role=user) NUNCA
// son redirigidos al wizard — ven el dashboard read-only directamente.

import { Navigate, useLocation } from "react-router-dom";
import { useSettings } from "./userMode";
import { useAuth } from "./AuthProvider";

const ALLOWED_WHEN_NOT_ONBOARDED = ["/onboarding", "/ayuda"];

export function OnboardingGate({ children }) {
    const { settings, loading } = useSettings();
    const { isAdmin, loading: authLoading } = useAuth();
    const location = useLocation();

    // Mientras carga settings por primera vez, no redirigimos — mostramos
    // skeleton/loading. Si tarda mucho, mejor que el usuario vea la UI a que
    // quede en blanco esperando.
    if ((loading && !settings) || authLoading) {
        return (
            <div
                className="min-h-screen flex items-center justify-center"
                data-testid="settings-loading"
            >
                <div className="kicker">// CARGANDO CONFIGURACIÓN…</div>
            </div>
        );
    }

    // No-admins NUNCA son forzados al wizard — solo ven el dashboard público.
    if (!isAdmin) {
        return children;
    }

    const onboarded = settings?.onboarded ?? true;
    const path = location.pathname;
    const isAllowed = ALLOWED_WHEN_NOT_ONBOARDED.some(
        (p) => path === p || path.startsWith(p + "/")
    );

    if (!onboarded && !isAllowed) {
        return <Navigate to="/onboarding" replace />;
    }

    return children;
}

// Helper inverso: si ya está onboarded y entra a /onboarding, lo manda a /
export function RedirectIfOnboarded({ children }) {
    const { settings, loading } = useSettings();
    if (loading && !settings) return null;
    if (settings?.onboarded) {
        return <Navigate to="/" replace />;
    }
    return children;
}
