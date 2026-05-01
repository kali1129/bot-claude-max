// Help — FAQ acordeón + ReferralBanner XM + tutorial paso a paso (placeholder).

import { LifeBuoy, MessageCircle, BookOpen } from "lucide-react";

import {
    Accordion,
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
} from "@/components/ui/accordion";

import SectionHeader from "@/components/atoms/SectionHeader";
import ReferralBanner from "@/components/atoms/ReferralBanner";

const FAQ = [
    {
        q: "¿El bot puede vaciarme la cuenta?",
        a: "No. Tiene un cap diario (default 3% de tu cuenta) y un cap por trade (default 1%). Si el día llega al cap, el bot se detiene solo. Además podés activar la parada de emergencia desde cualquier pantalla.",
    },
    {
        q: "¿Qué pasa si pierdo internet?",
        a: "Las operaciones que ya están abiertas tienen Stop Loss y Take Profit configurados directamente en MT5 — el broker los respeta sin importar si tu PC está conectada o no. El bot no podrá abrir nuevas hasta que vuelva la conexión.",
    },
    {
        q: "¿Cómo lo apago?",
        a: "Usá el botón rojo 'Detener Todo' (lo ves arriba a la derecha en cualquier pantalla). El bot deja de buscar oportunidades nuevas. Las posiciones abiertas siguen con sus SL/TP — si querés cerrarlas, hacelo desde MT5 directamente.",
    },
    {
        q: "¿Cuánto plata necesito para empezar?",
        a: "El bot funciona con cualquier capital. Te recomendamos empezar con $100-300 en cuenta demo o real chica para aprender cómo opera. La meta que pongas en Configuración solo afecta el sizing — el bot nunca arriesga más de lo configurado por trade.",
    },
    {
        q: "¿Qué diferencia hay entre Conservativo, Balanceado y Agresivo?",
        a: "Conservativo arriesga 0.5% por trade y abre solo 1 posición a la vez. Balanceado (recomendado) arriesga 1% y abre hasta 3. Agresivo arriesga 2% y abre hasta 5 — solo para experimentados, te avisamos antes de activarlo.",
    },
    {
        q: "¿Necesito tener el broker XM o sirve cualquiera?",
        a: "El bot funciona con cualquier broker que tenga MetaTrader 5. Recomendamos XM porque está integrado nativamente y abrir la cuenta es gratis — además, si abrís por nuestro link, nos ayudás a mantener el bot funcionando.",
    },
    {
        q: "¿Cómo conecto Telegram?",
        a: "En Configuración → Notificaciones. Te pide un chat ID — lo conseguís mandándole /my_id al bot de Telegram que te dieron. Cualquier persona con un chat ID configurado va a recibir avisos cuando se abra/cierre una operación.",
    },
    {
        q: "¿Qué es el modo Novato vs Experto?",
        a: "Novato muestra tooltips amigables, oculta métricas avanzadas (Sharpe, Sortino, etc) y simplifica la UI. Experto te da acceso a backtesting, optimizer, params crudos de cada estrategia, y métricas pro. Cambialo en Configuración → Mi Plan.",
    },
    {
        q: "¿Puedo ver los trades pasados del bot?",
        a: "Sí, en la sección Operaciones. Ahí ves cada trade cerrado con fecha, par, resultado y ganancia/pérdida. También podés registrar trades manuales si los hacés a mano.",
    },
    {
        q: "El bot dice 'PARADO' o 'PARCIAL' — ¿qué significa?",
        a: "Significa que alguno de los procesos (auto_trader o sync_loop) no está corriendo. Andá a Configuración → Avanzado → Procesos y arrancá los que están detenidos. Si recién instalaste, puede que falte el primer arranque.",
    },
];

export default function Help() {
    return (
        <section className="px-6 lg:px-10 py-8" data-testid="page-help">
            <div className="max-w-[1400px] mx-auto">
                <SectionHeader
                    code="07 / AYUDA"
                    title="Ayuda y Soporte"
                    subtitle="Preguntas frecuentes, tutoriales y links útiles."
                />

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                    {/* FAQ — col 2 wide */}
                    <div className="lg:col-span-2">
                        <div className="panel p-5">
                            <div className="kicker mb-3 flex items-center gap-2">
                                <LifeBuoy size={12} className="text-[var(--green)]" />
                                PREGUNTAS FRECUENTES
                            </div>
                            <Accordion type="single" collapsible className="space-y-1">
                                {FAQ.map((item, i) => (
                                    <AccordionItem
                                        key={i}
                                        value={`q${i}`}
                                        className="border-[var(--border)]"
                                    >
                                        <AccordionTrigger className="text-sm font-display font-semibold text-left">
                                            {item.q}
                                        </AccordionTrigger>
                                        <AccordionContent className="text-sm text-[var(--text-dim)] leading-relaxed">
                                            {item.a}
                                        </AccordionContent>
                                    </AccordionItem>
                                ))}
                            </Accordion>
                        </div>

                        {/* Tutorial placeholder */}
                        <div className="panel p-5 mt-4">
                            <div className="kicker mb-3 flex items-center gap-2">
                                <BookOpen size={12} className="text-[var(--blue)]" />
                                PRIMEROS PASOS
                            </div>
                            <div className="space-y-3 text-sm">
                                <Step
                                    n={1}
                                    title="Abrí cuenta con un broker"
                                    body="Recomendamos XM (gratis). Mirá el banner verde a la derecha."
                                />
                                <Step
                                    n={2}
                                    title="Conectá MT5 al bot"
                                    body="Configuración → Broker (MT5). Pegá login, password, server. Probá conexión y guardá."
                                />
                                <Step
                                    n={3}
                                    title="Ajustá tu meta y estilo"
                                    body="Configuración → Mi Plan. Ponele un goal realista y elegí Balanceado si dudás."
                                />
                                <Step
                                    n={4}
                                    title="Encendé el bot"
                                    body="Desde el Inicio o el Panel de Control. El bot arranca a escanear."
                                />
                                <Step
                                    n={5}
                                    title="Mirá Operaciones e Inicio"
                                    body="Cada trade que abra/cierre aparece ahí. Los avisos también van a Telegram si lo configuraste."
                                />
                            </div>
                        </div>
                    </div>

                    {/* Right column — referral + telegram */}
                    <div className="space-y-4">
                        <ReferralBanner variant="feature" />

                        <div className="panel p-5">
                            <div className="kicker mb-2 flex items-center gap-2">
                                <MessageCircle size={12} className="text-[var(--blue)]" />
                                TU CHAT ID DE TELEGRAM
                            </div>
                            <p className="text-xs text-[var(--text-dim)] mb-3 leading-relaxed">
                                Para recibir notificaciones, necesitás conseguir tu
                                chat ID. Mandale <code className="font-mono">/my_id</code>{" "}
                                al bot de Telegram que te dieron y copiá el número que
                                te responde. Después pegalo en Configuración →
                                Notificaciones.
                            </p>
                            <code className="codeblock block text-[10px]">
                                /my_id
                            </code>
                        </div>

                        <div className="panel p-5 stripes-warn">
                            <div className="kicker mb-2">PROGRAMA DE REFERIDOS</div>
                            <p className="text-xs text-[var(--text-dim)] leading-relaxed">
                                Si conocés a alguien que quiera tradear automatizado,
                                comparte tu link de afiliados de XM. Cuando abre cuenta
                                y deposita, ambos ganan. El link está en el banner
                                verde de arriba.
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    );
}

function Step({ n, title, body }) {
    return (
        <div className="flex gap-3">
            <div
                className="flex items-center justify-center w-7 h-7 flex-shrink-0 font-mono font-bold text-xs"
                style={{
                    background: "var(--green)",
                    color: "#000",
                }}
            >
                {n}
            </div>
            <div>
                <div className="font-display font-semibold">{title}</div>
                <div className="text-xs text-[var(--text-dim)] leading-relaxed">
                    {body}
                </div>
            </div>
        </div>
    );
}
