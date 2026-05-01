// HaltButton — botón de pánico + indicador de estado en vivo.
//
// Comportamiento previo (bug QA #1):
//   - Click halt → toast aparece, pero la UI no mostraba si quedó halted.
//   - No había forma de hacer "Resume" desde el botón.
//   - Si el usuario cambiaba de página, no veía el estado halted.
//
// Comportamiento ahora:
//   - Polling de /api/halt cada 3s → estado siempre fresco.
//   - Si halted=true: el botón muestra "REANUDAR" en verde (mismo botón).
//   - Si halted=false: muestra "Pausar" / "Detener Todo" en rojo.
//   - Modal de confirmación distinto según la acción (pausar vs reanudar).
//   - Tras la acción, refetch inmediato para feedback < 100ms.

import { useEffect, useState, useCallback } from "react";
import { ShieldAlert, ShieldCheck, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { apiPost, apiDelete, apiGet } from "@/lib/api";
import WarningModal from "./WarningModal";

const POLL_MS = 3000;

export default function HaltButton({ compact = false }) {
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const [halted, setHalted] = useState(null);     // null = loading, bool tras fetch
    const [reason, setReason] = useState("");

    const refresh = useCallback(async () => {
        try {
            const r = await apiGet("/halt");
            setHalted(!!r.data?.halted);
            setReason(r.data?.reason || "");
        } catch {
            // silent — mantener estado previo
        }
    }, []);

    useEffect(() => {
        refresh();
        const id = setInterval(refresh, POLL_MS);
        return () => clearInterval(id);
    }, [refresh]);

    const doHalt = async () => {
        setBusy(true);
        try {
            const r = await apiPost("/halt", { reason: "manual halt from dashboard" });
            if (r.data?.ok !== false) {
                setHalted(true);
                setReason(r.data?.reason || "manual");
                toast.success("🛑 Bot detenido. Las posiciones abiertas quedan en MT5.");
            } else {
                toast.error("No se pudo detener: " + (r.data?.reason || "error"));
            }
        } catch (e) {
            toast.error("No se pudo detener el bot");
            console.error(e);
        } finally {
            setBusy(false);
        }
    };

    const doResume = async () => {
        setBusy(true);
        try {
            const r = await apiDelete("/halt");
            if (r.data?.ok !== false) {
                setHalted(false);
                setReason("");
                toast.success("✅ Bot reanudado. Va a buscar nuevas operaciones.");
            } else {
                toast.error("No se pudo reanudar");
            }
        } catch (e) {
            toast.error("No se pudo reanudar el bot");
            console.error(e);
        } finally {
            setBusy(false);
        }
    };

    // Loading inicial: botón neutro con spinner
    if (halted === null) {
        return (
            <button
                type="button"
                disabled
                className={`btn-sharp flex items-center gap-2 ${compact ? "" : "btn-xl"}`}
                aria-label="Cargando estado del bot"
            >
                <Loader2 size={compact ? 12 : 16} className="animate-spin" />
                {compact ? "..." : "Cargando..."}
            </button>
        );
    }

    if (halted) {
        // Estado pausado: ofrece reanudar (verde)
        return (
            <>
                <button
                    type="button"
                    onClick={() => setOpen(true)}
                    disabled={busy}
                    className={`btn-sharp success flex items-center gap-2 ${compact ? "" : "btn-xl"}`}
                    aria-label="Reanudar bot"
                    data-testid="resume-button"
                    data-state="halted"
                    title={reason ? `Pausado: ${reason}` : "Pausado"}
                >
                    {busy ? (
                        <Loader2 size={compact ? 12 : 16} className="animate-spin" />
                    ) : (
                        <ShieldCheck size={compact ? 12 : 16} />
                    )}
                    {compact ? "Reanudar" : "Reanudar Bot"}
                </button>
                <WarningModal
                    open={open}
                    onOpenChange={setOpen}
                    title="¿Reanudar el bot?"
                    body={
                        <div className="space-y-2 text-sm">
                            <p>
                                El bot va a empezar a buscar nuevas operaciones de
                                inmediato según tu estilo y sesión configurada.
                            </p>
                            {reason ? (
                                <p className="text-[var(--text-faint)] font-mono text-xs">
                                    Motivo del pause anterior: {reason}
                                </p>
                            ) : null}
                        </div>
                    }
                    confirmLabel="Sí, reanudar"
                    cancelLabel="Cancelar"
                    onConfirm={doResume}
                />
            </>
        );
    }

    // Estado activo: ofrece pausar (rojo)
    return (
        <>
            <button
                type="button"
                onClick={() => setOpen(true)}
                disabled={busy}
                className={`btn-sharp danger flex items-center gap-2 ${compact ? "" : "btn-xl"}`}
                aria-label="Detener bot inmediatamente"
                data-testid="halt-button"
                data-state="active"
            >
                {busy ? (
                    <Loader2 size={compact ? 12 : 16} className="animate-spin" />
                ) : (
                    <ShieldAlert size={compact ? 12 : 16} />
                )}
                {compact ? "Pausar" : "Detener Todo"}
            </button>
            <WarningModal
                open={open}
                onOpenChange={setOpen}
                title="¿Detener el bot ahora?"
                body={
                    <div className="space-y-2 text-sm">
                        <p>
                            El bot va a dejar de abrir nuevas operaciones. Las
                            posiciones que ya están abiertas <strong>NO se cierran</strong>{" "}
                            — quedan en MT5 con su SL/TP.
                        </p>
                        <p className="text-[var(--text-faint)]">
                            Podés reanudar desde acá mismo cuando quieras.
                        </p>
                    </div>
                }
                checkboxText="Entiendo. Las posiciones abiertas se mantienen."
                confirmLabel="Sí, detener bot"
                cancelLabel="Cancelar"
                danger
                onConfirm={doHalt}
            />
        </>
    );
}
