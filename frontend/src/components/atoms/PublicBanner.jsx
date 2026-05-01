// PublicBanner — banner persistente arriba del dashboard que avisa al
// visitante anónimo que está viendo una DEMO pública del bot del admin
// + CTA para registrarse y eventualmente conectar SU propia cuenta XM.
//
// FASE 1: el dashboard público es read-only. Cualquiera puede ver el bot
// del admin operar en vivo, pero no modificar nada. Para la FASE 2 (cada
// user con su propio bot), el banner cambiará a "Conectá tu cuenta MT5".

import { Link } from "react-router-dom";
import { Eye, ExternalLink, UserPlus, ChevronRight } from "lucide-react";
import { useAuth } from "@/lib/AuthProvider";

const XM_REFERRAL = "https://www.xmglobal.com/referral?token=OtZfgkRKCdH25RlT1gJ7hQ";

export default function PublicBanner() {
    const { user, isAuthenticated, isAdmin, loading } = useAuth();

    // No mostramos nada al admin ni mientras carga.
    if (loading || isAdmin) return null;

    // Anónimo: banner full con CTA login + register + XM.
    if (!isAuthenticated) {
        return (
            <div
                className="px-4 py-2 border-b border-[var(--border)]"
                style={{
                    background:
                        "linear-gradient(90deg, rgba(16,185,129,0.06) 0%, rgba(59,130,246,0.06) 100%)",
                }}
                data-testid="public-banner-anon"
            >
                <div className="max-w-[1400px] mx-auto flex flex-wrap items-center gap-3 justify-between">
                    <div className="flex items-center gap-2 text-xs">
                        <Eye size={12} className="text-[var(--green-bright)]" />
                        <span className="font-mono">
                            <span className="text-[var(--green-bright)] font-bold">
                                MODO DEMO PÚBLICO
                            </span>
                            <span className="text-[var(--text-dim)] ml-2 hidden md:inline">
                                · estás viendo el bot funcionando en vivo (sin posibilidad de modificarlo)
                            </span>
                        </span>
                    </div>
                    <div className="flex items-center gap-2">
                        <Link
                            to="/register"
                            className="btn-sharp flex items-center gap-1 text-[10px]"
                        >
                            <UserPlus size={11} />
                            Crear cuenta
                        </Link>
                        <a
                            href={XM_REFERRAL}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="btn-sharp success flex items-center gap-1 text-[10px]"
                            data-testid="public-banner-xm"
                        >
                            <ExternalLink size={11} />
                            <span className="hidden md:inline">Crear cuenta XM</span>
                            <span className="md:hidden">XM</span>
                            <ChevronRight size={11} />
                        </a>
                    </div>
                </div>
            </div>
        );
    }

    // Logged user (no admin): banner reducido — recordatorio de modo demo.
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
