// UserModeBadge — pill clickeable que muestra el modo actual y permite
// cambiarlo. PUT /api/settings { mode }.

import { useState } from "react";
import { ChevronDown, GraduationCap, Wrench } from "lucide-react";
import { useSettings } from "@/lib/userMode";
import {
    DropdownMenu,
    DropdownMenuTrigger,
    DropdownMenuContent,
    DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";

export default function UserModeBadge({ compact = false }) {
    const { settings, updateSettings, isNovato } = useSettings();
    const [busy, setBusy] = useState(false);
    const mode = settings?.mode || "novato";

    const change = async (next) => {
        if (next === mode) return;
        setBusy(true);
        try {
            await updateSettings({ mode: next });
            toast.success(
                next === "novato"
                    ? "Modo Novato activado"
                    : "Modo Experto activado"
            );
        } catch (e) {
            toast.error("No se pudo cambiar el modo");
        } finally {
            setBusy(false);
        }
    };

    const Icon = isNovato ? GraduationCap : Wrench;
    const label = isNovato ? "Novato" : "Experto";
    const color = isNovato ? "var(--novato-accent)" : "var(--green-bright)";

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <button
                    type="button"
                    disabled={busy}
                    className="btn-sharp flex items-center gap-2"
                    data-testid="user-mode-badge"
                    style={{ borderColor: color, color }}
                    aria-label={`Modo actual: ${label}. Click para cambiar.`}
                >
                    <Icon size={12} />
                    {!compact && <span>{label}</span>}
                    <ChevronDown size={12} />
                </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="bg-[var(--surface)] border-[var(--border)]">
                <DropdownMenuItem
                    onClick={() => change("novato")}
                    className="font-mono text-xs"
                    data-testid="set-mode-novato"
                >
                    <GraduationCap size={12} className="mr-2" />
                    Novato
                    <span className="ml-2 text-[var(--text-faint)]">— guiado, simplificado</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                    onClick={() => change("experto")}
                    className="font-mono text-xs"
                    data-testid="set-mode-experto"
                >
                    <Wrench size={12} className="mr-2" />
                    Experto
                    <span className="ml-2 text-[var(--text-faint)]">— métricas pro, params crudos</span>
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
