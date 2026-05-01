// WarningModal — Dialog forzado (no cierra con click outside) con checkbox
// obligatorio + botón Confirm deshabilitado hasta marcar el check.

import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
} from "@/components/ui/dialog";

export default function WarningModal({
    open,
    onOpenChange,
    title,
    body,
    checkboxText,
    onConfirm,
    onCancel,
    confirmLabel = "Confirmar",
    cancelLabel = "Cancelar",
    danger = false,
}) {
    const [checked, setChecked] = useState(false);

    // Reset el checkbox cuando se reabre el modal
    useEffect(() => {
        if (open) setChecked(false);
    }, [open]);

    const accent = danger ? "var(--red)" : "var(--amber)";

    const handleOpenChange = (next) => {
        if (!next) {
            // No permitir cerrar con backdrop si tiene checkbox obligatorio:
            // usuario tiene que clickear cancelar explícitamente.
            if (checkboxText) return;
            onCancel?.();
            onOpenChange?.(false);
        } else {
            onOpenChange?.(true);
        }
    };

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogContent
                className="bg-[var(--surface)] border border-[var(--border-strong)] text-[var(--text)] max-w-lg"
                onPointerDownOutside={(e) => {
                    // bloqueamos cierre con click fuera
                    if (checkboxText) e.preventDefault();
                }}
                onEscapeKeyDown={(e) => {
                    if (checkboxText) e.preventDefault();
                }}
            >
                <DialogHeader>
                    <DialogTitle
                        className="flex items-center gap-3 font-display text-xl font-bold"
                        style={{ color: accent }}
                    >
                        <AlertTriangle size={22} />
                        {title}
                    </DialogTitle>
                    {body && typeof body === "string" ? (
                        <DialogDescription className="text-sm text-[var(--text-dim)] leading-relaxed">
                            {body}
                        </DialogDescription>
                    ) : (
                        <div className="text-sm text-[var(--text-dim)] leading-relaxed">
                            {body}
                        </div>
                    )}
                </DialogHeader>

                {checkboxText ? (
                    <label className="flex items-start gap-2 cursor-pointer mt-2">
                        <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => setChecked(e.target.checked)}
                            className="mt-1"
                            data-testid="warning-checkbox"
                        />
                        <span className="text-sm text-[var(--text)]">
                            {checkboxText}
                        </span>
                    </label>
                ) : null}

                <DialogFooter className="gap-2 mt-3">
                    <button
                        type="button"
                        onClick={() => {
                            onCancel?.();
                            onOpenChange?.(false);
                        }}
                        className="btn-sharp primary"
                        data-testid="warning-cancel"
                    >
                        {cancelLabel}
                    </button>
                    <button
                        type="button"
                        disabled={!!checkboxText && !checked}
                        onClick={() => {
                            onConfirm?.();
                            onOpenChange?.(false);
                        }}
                        className={`btn-sharp ${danger ? "danger" : ""}`}
                        data-testid="warning-confirm"
                    >
                        {confirmLabel}
                    </button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
