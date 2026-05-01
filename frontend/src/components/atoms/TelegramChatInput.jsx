// TelegramChatInput — input + botón "Agregar" + lista de chats actuales con
// delete + accordion explicativo de cómo conseguir el chat_id.

import { useState } from "react";
import { Plus, Trash2, Send } from "lucide-react";
import { toast } from "sonner";
import { apiPost } from "@/lib/api";
import {
    Accordion,
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
} from "@/components/ui/accordion";

export default function TelegramChatInput({
    chats = [],
    onChange,
}) {
    const [val, setVal] = useState("");
    const [busy, setBusy] = useState(false);

    const add = async () => {
        const id = parseInt(val.trim(), 10);
        if (!Number.isInteger(id)) {
            toast.error("El chat ID tiene que ser un número entero");
            return;
        }
        if ((chats || []).includes(id)) {
            toast.info("Ese chat ya está en la lista");
            return;
        }
        setBusy(true);
        try {
            await apiPost("/settings/telegram/add", { chat_id: id });
            toast.success(`Chat ${id} agregado`);
            setVal("");
            onChange?.();
        } catch (e) {
            toast.error("No se pudo agregar el chat");
            console.error(e);
        } finally {
            setBusy(false);
        }
    };

    const remove = async (id) => {
        setBusy(true);
        try {
            await apiPost("/settings/telegram/remove", { chat_id: id });
            toast.success(`Chat ${id} eliminado`);
            onChange?.();
        } catch (e) {
            toast.error("No se pudo eliminar el chat");
            console.error(e);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="space-y-3" data-testid="telegram-chat-input">
            <div className="flex gap-2">
                <input
                    type="text"
                    inputMode="numeric"
                    placeholder="123456789"
                    value={val}
                    onChange={(e) => setVal(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === "Enter") {
                            e.preventDefault();
                            add();
                        }
                    }}
                    className="input-sharp flex-1"
                    aria-label="Chat ID de Telegram"
                />
                <button
                    type="button"
                    onClick={add}
                    disabled={busy || !val.trim()}
                    className="btn-sharp primary flex items-center gap-2"
                    data-testid="telegram-add-btn"
                >
                    <Plus size={12} />
                    Agregar
                </button>
            </div>

            {(chats || []).length > 0 ? (
                <div className="space-y-1">
                    {chats.map((id) => (
                        <div
                            key={id}
                            className="flex items-center justify-between px-3 py-2 panel"
                        >
                            <div className="flex items-center gap-2 font-mono text-sm">
                                <Send size={12} className="text-[var(--green)]" />
                                {id}
                            </div>
                            <button
                                type="button"
                                onClick={() => remove(id)}
                                aria-label={`Eliminar chat ${id}`}
                                className="text-[var(--text-faint)] hover:text-[var(--red)]"
                                data-testid={`telegram-remove-${id}`}
                            >
                                <Trash2 size={14} />
                            </button>
                        </div>
                    ))}
                </div>
            ) : (
                <div className="text-xs text-[var(--text-faint)] font-mono italic">
                    No hay chats configurados todavía.
                </div>
            )}

            <Accordion type="single" collapsible>
                <AccordionItem value="how" className="border-[var(--border)]">
                    <AccordionTrigger className="text-xs font-mono">
                        ¿Cómo encuentro mi chat ID?
                    </AccordionTrigger>
                    <AccordionContent className="text-xs text-[var(--text-dim)] space-y-2">
                        <ol className="list-decimal list-inside space-y-1.5 leading-relaxed">
                            <li>
                                Abrí Telegram y buscá el bot que te dieron (o creá
                                uno con <code className="font-mono">@BotFather</code>).
                            </li>
                            <li>
                                Mandale el comando <code className="font-mono">/start</code> al
                                bot.
                            </li>
                            <li>
                                Después mandá <code className="font-mono">/my_id</code>.
                            </li>
                            <li>
                                Copiá el número que te responde y pegalo arriba.
                            </li>
                        </ol>
                        <p className="pt-1">
                            Cualquier persona con un chat ID configurado va a recibir
                            avisos cuando el bot abra/cierre operaciones.
                        </p>
                    </AccordionContent>
                </AccordionItem>
            </Accordion>
        </div>
    );
}
