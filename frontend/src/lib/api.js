// Wrapper centralizado para llamadas axios al backend del trading bot.
// Antes: cada componente declaraba `process.env.REACT_APP_BACKEND_URL` y
// `REACT_APP_DASHBOARD_TOKEN` por su cuenta. Ahora todo pasa por acá.

import axios from "axios";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";
const TOKEN = process.env.REACT_APP_DASHBOARD_TOKEN || "";

// Base URL absoluta hacia /api del backend
export const API_BASE = `${BACKEND}/api`;

// Instancia axios con interceptor — el header Authorization solo aplica
// a métodos write (POST/PUT/DELETE/PATCH). Para GET no es necesario.
const api = axios.create({
    baseURL: API_BASE,
    timeout: 15000,
});

api.interceptors.request.use((config) => {
    const method = (config.method || "get").toLowerCase();
    if (["post", "put", "patch", "delete"].includes(method) && TOKEN) {
        config.headers = config.headers || {};
        if (!config.headers["Authorization"]) {
            config.headers["Authorization"] = `Bearer ${TOKEN}`;
        }
    }
    return config;
});

// Helpers cortos por verbo, igual que axios pero usando la instancia.
export const apiGet = (path, opts) => api.get(path, opts);
export const apiPost = (path, body, opts) => api.post(path, body, opts);
export const apiPut = (path, body, opts) => api.put(path, body, opts);
export const apiDelete = (path, opts) => api.delete(path, opts);
export const apiPatch = (path, body, opts) => api.patch(path, body, opts);

export default api;
