// AggressiveBanner — banner persistente arriba del TopBar cuando style=agresivo.
// No es cerrable. Solo desaparece si cambia el estilo desde Configuración.

import { AlertTriangle } from "lucide-react";
import { Link } from "react-router-dom";
import { useSettings } from "@/lib/userMode";

export default function AggressiveBanner() {
    const { settings } = useSettings();
    if (settings?.style !== "agresivo") return null;

    return (
        <div
            className="banner-warn flex items-center gap-3 text-xs font-mono flex-wrap"
            data-testid="aggressive-banner"
            role="alert"
        >
            <AlertTriangle size={14} className="text-[var(--warn)] flex-shrink-0" />
            <span className="text-[var(--text)] font-semibold">
                Modo Agresivo activo
            </span>
            <span className="text-[var(--text-dim)]">
                · 2% de riesgo por operación
            </span>
            <Link
                to="/configuracion"
                className="ml-auto text-[var(--green-bright)] underline"
            >
                Cambiar a balanceado
            </Link>
        </div>
    );
}
