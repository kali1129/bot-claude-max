// SettingsContext / userMode provider.
//
// Una sola fuente de verdad para `/api/settings`. Cualquier componente
// que necesite saber si el usuario es novato o experto, qué meta tiene,
// qué estilo está activo, etc., consume este contexto. Los cambios
// PUT al backend invalidan el cache y refetchean.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { apiGet, apiPut, apiPost } from "./api";

const SettingsContext = createContext({
    settings: null,
    loading: true,
    error: null,
    isNovato: true,
    isExperto: false,
    refresh: async () => {},
    updateSettings: async () => {},
    completeOnboarding: async () => {},
});

export function SettingsProvider({ children }) {
    const [settings, setSettings] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const refresh = useCallback(async () => {
        try {
            setError(null);
            const res = await apiGet("/settings");
            setSettings(res.data);
        } catch (e) {
            // Si el backend está caído, el dashboard sigue funcionando con
            // valores por defecto novato. No reventamos toda la UI.
            console.error("settings fetch error", e);
            setError(e);
            setSettings((prev) => prev || defaultSettings());
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        refresh();
    }, [refresh]);

    const updateSettings = useCallback(
        async (patch) => {
            // Optimistic update local + PUT
            setSettings((prev) => ({ ...(prev || {}), ...patch }));
            try {
                const res = await apiPut("/settings", patch);
                setSettings(res.data);
                return res.data;
            } catch (e) {
                console.error("settings update error", e);
                // Re-fetch para volver al estado server
                refresh();
                throw e;
            }
        },
        [refresh]
    );

    const completeOnboarding = useCallback(async () => {
        try {
            await apiPost("/settings/onboarding/complete");
        } catch (e) {
            console.error("onboarding/complete error", e);
        }
        await refresh();
    }, [refresh]);

    const value = useMemo(() => {
        const mode = settings?.mode || "novato";
        return {
            settings,
            loading,
            error,
            isNovato: mode === "novato",
            isExperto: mode === "experto",
            refresh,
            updateSettings,
            completeOnboarding,
        };
    }, [settings, loading, error, refresh, updateSettings, completeOnboarding]);

    return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings() {
    return useContext(SettingsContext);
}

// Atajo cuando solo querés saber el modo
export function useUserMode() {
    const { isNovato, isExperto, settings } = useContext(SettingsContext);
    return { isNovato, isExperto, mode: settings?.mode || "novato" };
}

// Defaults defensivos cuando el backend no responde — para que la UI no quede
// muerta. Mode novato + onboarded=true (no forzamos wizard si no podemos
// confirmar el flag desde el server).
function defaultSettings() {
    return {
        mode: "novato",
        goal_usd: null,
        style: "balanceado",
        sessions: ["24/7"],
        telegram_chat_ids: [],
        telegram_enabled: false,
        referral_partner: {
            broker: "xm",
            url: "https://www.xm.com/",
            label: "XM Global",
        },
        onboarded: true,
        active_style_preset: {
            risk_pct: 1.0,
            max_pos: 3,
            max_daily_loss_pct: 3.0,
            min_rr: 2.0,
        },
        available_styles: {},
        available_sessions: {},
    };
}
