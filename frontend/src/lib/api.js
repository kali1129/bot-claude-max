// Wrapper centralizado para llamadas axios al backend del trading bot.
//
// FASE 1: el header Authorization ahora se construye con el JWT del
// localStorage (post login) y NO con el env var compartido. Esto evita
// que el bundle JS leak el "admin token" — antes cualquiera que viera
// el HTML obtenía control total.
//
// Si NO hay JWT: el header NO se envía. Las requests a endpoints
// protegidos van a fallar 401, que el caller debe manejar (redirect a
// /login).

import axios from "axios";
import { getToken, clearSession } from "./auth";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

// Base URL absoluta hacia /api del backend
export const API_BASE = `${BACKEND}/api`;

const api = axios.create({
    baseURL: API_BASE,
    timeout: 15000,
});

// REQUEST: agrega Bearer JWT si hay sesión. Aplica a TODOS los métodos
// (read y write) — el backend ignora el header en endpoints públicos.
api.interceptors.request.use((config) => {
    const t = getToken();
    if (t) {
        config.headers = config.headers || {};
        if (!config.headers["Authorization"]) {
            config.headers["Authorization"] = `Bearer ${t}`;
        }
    }
    return config;
});

// RESPONSE: si el server devuelve 401 (token expirado/inválido), limpia
// la sesión y deja que el caller redirija a /login. Para 403 (rol
// insuficiente) NO limpiamos — el usuario sigue logueado pero ese
// endpoint en particular es admin-only.
api.interceptors.response.use(
    (r) => r,
    (e) => {
        if (e.response?.status === 401) {
            const token = getToken();
            if (token) {
                clearSession();
                // No forzamos navegación acá — el AuthProvider detecta y
                // redirige. Reload suave si estamos en una ruta protegida:
                if (typeof window !== "undefined") {
                    window.dispatchEvent(new CustomEvent("auth:expired"));
                }
            }
        }
        return Promise.reject(e);
    },
);

// Helpers cortos por verbo, igual que axios pero usando la instancia.
export const apiGet = (path, opts) => api.get(path, opts);
export const apiPost = (path, body, opts) => api.post(path, body, opts);
export const apiPut = (path, body, opts) => api.put(path, body, opts);
export const apiDelete = (path, opts) => api.delete(path, opts);
export const apiPatch = (path, body, opts) => api.patch(path, body, opts);

export default api;
