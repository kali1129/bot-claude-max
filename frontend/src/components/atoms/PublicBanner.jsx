// PublicBanner — banner hero arriba del dashboard.
//
// Anónimo: banner GRANDE con 3 cards explicando los modos de acceso:
//   1. "Solo mirar" — sin registro, ver el bot del admin operar.
//   2. "Crear cuenta sin broker" — sandbox, settings ficticios.
//   3. "Operar con XM" — registrá XM con afiliado + conectá MT5 (Fase 2).
//
// Logged user (no admin): banner reducido recordatorio.
// Admin: nada (no se muestra).
//
// El banner es DISMISSIBLE — el usuario puede colapsarlo, se guarda
// en localStorage para que no reaparezca cada vez.

import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import {
    Eye, ExternalLink, UserPlus, ChevronRight, X, Sparkles, LogIn,
} from "lucide-react";
import { useAuth } from "@/lib/AuthProvider";

const XM_REFERRAL = "https://www.xmglobal.com/referral?token=OtZfgkRKCdH25RlT1gJ7hQ";
const COLLAPSED_KEY = "bot_banner_collapsed_v1";

export default function PublicBanner() {
    const { user, isAuthenticated, isAdmin, loading } = useAuth();
    const [collapsed, setCollapsed] = useState(false);

    useEffect(() => {
        try {
            setCollapsed(localStorage.getItem(COLLAPSED_KEY) === "1");
        } catch {
            // noop
        }
    }, []);

    const toggleCollapse = () => {
        const next = !collapsed;
        setCollapsed(next);
        try {
            localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
        } catch {
            // noop
        }
    };

    if (loading || isAdmin) return null;

    // Logged user (no admin): banner reducido.
    if (isAuthenticated) {
        return (
            <div
                className="px-4 py-1.5 border-b border-[var(--border)] text-[10px]"
                style={{ background: "rgba(59, 130, 246, 0.06)" }}
                data-testid="public-banner-user"
            >
                <div className="max-w-[1400px] mx-auto flex flex-wrap items-center justify-between gap-2">
                    <div className="font-mono">
                        <span className="text-[var(--blue)] font-bold">DEMO</span>{" "}
                        <span className="text-[var(--text-dim)]">
                            Hola {user?.display_name || user?.email?.split("@")[0]} 👋 ·
                            estás viendo el bot del admin. Pronto vas a poder
                            conectar tu propia cuenta.
                        </span>
                    </div>
                    <a
                        href={XM_REFERRAL}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[var(--green-bright)] hover:underline font-mono flex items-center gap-1"
                    >
                        Crear cuenta XM <ExternalLink size={10} />
                    </a>
                </div>
            </div>
        );
    }

    // Anónimo y colapsado: barra fina con CTA expandir.
    if (collapsed) {
        return (
            <div
                className="px-4 py-2 border-b border-[var(--border)] cursor-pointer hover:bg-[var(--surface)]"
                style={{
                    background:
                        "linear-gradient(90deg, rgba(16,185,129,0.08) 0%, rgba(59,130,246,0.08) 100%)",
                }}
                data-testid="public-banner-collapsed"
                onClick={toggleCollapse}
            >
                <div className="max-w-[1400px] mx-auto flex items-center gap-3 justify-between text-xs">
                    <div className="flex items-center gap-2 font-mono">
                        <Eye size={12} className="text-[var(--green-bright)]" />
                        <span className="text-[var(--green-bright)] font-bold">MODO DEMO</span>
                        <span className="text-[var(--text-dim)] hidden md:inline">
                            · click para ver opciones de acceso
                        </span>
                    </div>
                    <ChevronRight size={12} className="text-[var(--text-faint)]" />
                </div>
            </div>
        );
    }

    // Anónimo y expandido: HERO BANNER con 3 modos.
    return (
        <div
            className="border-b border-[var(--border)]"
            style={{
                background:
                    "linear-gradient(135deg, rgba(16,185,129,0.10) 0%, rgba(59,130,246,0.10) 50%, rgba(16,185,129,0.06) 100%)",
            }}
            data-testid="public-banner-anon"
        >
            <div className="max-w-[1400px] mx-auto px-4 lg:px-8 py-6 lg:py-8 relative">
                {/* Botón colapsar */}
                <button
                    type="button"
                    onClick={toggleCollapse}
                    className="absolute top-3 right-3 text-[var(--text-faint)] hover:text-white p-1"
                    aria-label="Colapsar banner"
                    data-testid="public-banner-collapse"
                >
                    <X size={14} />
                </button>

                {/* Header con CTA Login prominente a la derecha */}
                <div className="flex items-start justify-between gap-4 flex-wrap mb-3">
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-2">
                            <Eye size={14} className="text-[var(--green-bright)]" />
                            <span className="kicker text-[var(--green-bright)] font-bold tracking-widest">
                                // MODO DEMO PÚBLICO
                            </span>
                        </div>
                        <h2 className="font-display text-2xl lg:text-3xl font-black mb-1 leading-tight">
                            Estás viendo el bot operar en vivo
                        </h2>
                    </div>
                    <Link
                        to="/login"
                        className="btn-sharp primary btn-xl flex items-center gap-2 mr-8"
                        data-testid="banner-login-cta"
                    >
                        <LogIn size={14} />
                        Iniciar sesión
                    </Link>
                </div>
                <p className="text-sm text-[var(--text-dim)] mb-5 max-w-[640px]">
                    Esta es la cuenta del admin del proyecto. Vos podés mirar
                    todo en tiempo real, pero <strong>no podés modificar
                    nada</strong> porque no es tu cuenta. Si querés probar el
                    bot, elegí una opción:
                </p>

                {/* 3 cards de modos de acceso */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-4">
                    {/* Modo 1: solo mirar */}
                    <div className="panel p-4 border-[var(--border)]">
                        <div className="flex items-center gap-2 mb-2">
                            <Eye
                                size={14}
                                className="text-[var(--text-dim)]"
                            />
                            <div className="kicker">OPCIÓN 1</div>
                        </div>
                        <div className="font-display text-base font-bold mb-1.5">
                            Solo mirar
                        </div>
                        <p className="text-[11px] text-[var(--text-dim)] leading-relaxed mb-3">
                            No te registres. Mirá el dashboard, las
                            operaciones, las estadísticas. Todo en vivo, sin
                            tocar nada.
                        </p>
                        <button
                            type="button"
                            onClick={toggleCollapse}
                            className="btn-sharp text-[10px] w-full flex items-center justify-center gap-1"
                            data-testid="banner-mode-watch"
                        >
                            Cerrar este aviso
                        </button>
                    </div>

                    {/* Modo 2: cuenta sandbox */}
                    <div
                        className="panel p-4"
                        style={{
                            borderColor: "var(--blue)",
                            background: "rgba(59,130,246,0.04)",
                        }}
                    >
                        <div className="flex items-center gap-2 mb-2">
                            <UserPlus size={14} className="text-[var(--blue)]" />
                            <div className="kicker text-[var(--blue)]">
                                OPCIÓN 2
                            </div>
                        </div>
                        <div className="font-display text-base font-bold mb-1.5">
                            Crear cuenta sin broker
                        </div>
                        <p className="text-[11px] text-[var(--text-dim)] leading-relaxed mb-3">
                            Probá con datos ficticios. Sin XM, sin MT5, sin
                            riesgo. Vas a ver cómo funciona la web y guardar
                            tu config personal.
                        </p>
                        <Link
                            to="/register"
                            className="btn-sharp text-[10px] w-full flex items-center justify-center gap-1"
                            style={{
                                borderColor: "var(--blue)",
                                color: "var(--blue)",
                            }}
                            data-testid="banner-mode-sandbox"
                        >
                            <UserPlus size={11} />
                            Crear cuenta gratis
                        </Link>
                    </div>

                    {/* Modo 3: operar con XM (Fase 2 — pendiente) */}
                    <div
                        className="panel p-4"
                        style={{
                            borderColor: "var(--green)",
                            background: "rgba(16,185,129,0.06)",
                        }}
                    >
                        <div className="flex items-center gap-2 mb-2">
                            <Sparkles
                                size={14}
                                className="text-[var(--green-bright)]"
                            />
                            <div className="kicker text-[var(--green-bright)]">
                                OPCIÓN 3 · RECOMENDADA
                            </div>
                        </div>
                        <div className="font-display text-base font-bold mb-1.5">
                            Probar con tu cuenta XM
                        </div>
                        <p className="text-[11px] text-[var(--text-dim)] leading-relaxed mb-3">
                            Probá el bot con tu propia cuenta XM, en lugar de
                            datos ficticios. Funciona con tu cuenta{" "}
                            <strong className="text-white">demo</strong>{" "}
                            (sin riesgo, $100k virtuales) o con tu cuenta{" "}
                            <strong className="text-white">real</strong>{" "}
                            (con dinero real). Vos elegís cuál conectar.
                        </p>
                        <p className="text-[10px] text-[var(--text-faint)] mb-3 italic">
                            ¿No tenés cuenta XM aún? Creala gratis en 2 min ↓
                        </p>
                        <a
                            href={XM_REFERRAL}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="btn-sharp success text-[10px] w-full flex items-center justify-center gap-1"
                            data-testid="banner-mode-xm"
                        >
                            <ExternalLink size={11} />
                            Crear cuenta XM →
                        </a>
                    </div>
                </div>

                {/* Footer micro */}
                <div className="mt-4 text-[10px] text-[var(--text-faint)] text-center md:text-right">
                    El bot opera sobre cuentas demo durante este período de prueba — sin riesgo real.
                </div>
            </div>
        </div>
    );
}
