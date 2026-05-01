// HaltButton — botón rojo grande para activar el kill switch.
// Llama a POST /api/halt con confirmación.

import { useState } from "react";
import { ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { apiPost } from "@/lib/api";
import WarningModal from "./WarningModal";

export default function HaltButton({ compact = false }) {
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState(false);

    const halt = async () => {
        setBusy(true);
        try {
            await apiPost("/halt");
            toast.success("Bot detenido. Todas las posiciones quedan abiertas.");
        } catch (e) {
            toast.error("No se pudo activar el halt");
            console.error(e);
        } finally {
            setBusy(false);
        }
    };

    return (
        <>
            <button
                type="button"
                onClick={() => setOpen(true)}
                disabled={busy}
                className={`btn-sharp danger flex items-center gap-2 ${compact ? "" : "btn-xl"}`}
                aria-label="Detener bot inmediatamente"
                data-testid="halt-button"
            >
                <ShieldAlert size={compact ? 12 : 16} />
                {compact ? "Pausar" : "Detener Todo"}
            </button>
            <WarningModal
                open={open}
                onOpenChange={setOpen}
                title="¿Detener el bot ahora?"
                body={
                    <div className="space-y-2">
                        <p>
                            El bot va a dejar de abrir nuevas operaciones. Las
                            posiciones que ya están abiertas <strong>NO se cierran</strong>{" "}
                            — quedan en MT5 con su SL/TP.
                        </p>
                        <p className="text-[var(--text-faint)]">
                            Podés reactivar el bot desde el Panel de Control.
                        </p>
                    </div>
                }
                checkboxText="Entiendo. Las posiciones abiertas se mantienen."
                confirmLabel="Sí, detener bot"
                cancelLabel="Cancelar"
                danger
                onConfirm={halt}
            />
        </>
    );
}
