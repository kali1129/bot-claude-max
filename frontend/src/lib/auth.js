// auth.js — gestión del JWT en el cliente.
//
// FASE 1 del plan multi-tenant: reemplaza el patrón anterior donde el
// `REACT_APP_DASHBOARD_TOKEN` se baked into the JS bundle al build time
// (cualquiera con el HTML podía extraerlo). Ahora cada usuario hace
// login → recibe JWT → se guarda en localStorage → se manda en cada
// request via Authorization header.
//
// Storage key: `bot_jwt`. Si no existe, el cliente está en modo "público
// read-only".

const STORAGE_KEY = "bot_jwt";
const USER_KEY = "bot_user";

export function getToken() {
    try {
        return localStorage.getItem(STORAGE_KEY) || null;
    } catch {
        return null;
    }
}

export function getUser() {
    try {
        const raw = localStorage.getItem(USER_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch {
        return null;
    }
}

export function setSession(token, user) {
    try {
        localStorage.setItem(STORAGE_KEY, token);
        if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
    } catch (e) {
        console.error("auth setSession failed", e);
    }
}

export function clearSession() {
    try {
        localStorage.removeItem(STORAGE_KEY);
        localStorage.removeItem(USER_KEY);
    } catch {
        // noop
    }
}

export function isAuthenticated() {
    return !!getToken();
}

export function isAdmin() {
    const u = getUser();
    return !!u && u.role === "admin";
}

// Decodificar el payload del JWT (sin verificar firma — solo para leer
// expiración + role en el cliente). Si parsing falla, retorna null.
export function decodeToken(token) {
    if (!token) return null;
    try {
        const parts = token.split(".");
        if (parts.length !== 3) return null;
        const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
        return JSON.parse(atob(payload));
    } catch {
        return null;
    }
}

export function isExpired(token) {
    const payload = decodeToken(token);
    if (!payload || !payload.exp) return false;
    // exp en segundos
    return Date.now() / 1000 > payload.exp;
}
