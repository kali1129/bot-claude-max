// NovatoTooltip — wrapper de cualquier label técnico.
//   · En modo experto: pass-through (renderiza children sin nada extra).
//   · En modo novato: agrega icono (?) con popup explicativo del término.
// Diccionario centralizado en lib/glossary.js

import { HelpCircle } from "lucide-react";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip";
import { useUserMode } from "@/lib/userMode";
import { GLOSSARY } from "@/lib/glossary";

export default function NovatoTooltip({ term, children, friendly = false }) {
    const { isNovato } = useUserMode();
    const entry = GLOSSARY[term?.toLowerCase?.()];

    // En experto, no mostramos tooltip
    if (!isNovato || !entry) {
        return children;
    }

    // En novato, si friendly=true reemplazamos el children por la etiqueta
    // amigable del diccionario.
    const displayed = friendly ? entry.label : children;

    return (
        <TooltipProvider delayDuration={200}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <span
                        className="tooltip-novato inline-flex items-center gap-1"
                        tabIndex={0}
                    >
                        {displayed}
                        <HelpCircle size={11} className="opacity-70" aria-label="Ayuda" />
                    </span>
                </TooltipTrigger>
                <TooltipContent
                    side="top"
                    className="max-w-xs bg-[var(--surface-2)] text-[var(--text)] border border-[var(--border)] px-3 py-2 text-xs"
                >
                    <div className="font-semibold mb-1">{entry.label}</div>
                    <div className="text-[var(--text-dim)] leading-snug">{entry.body}</div>
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}
