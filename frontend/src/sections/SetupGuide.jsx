export default function SetupGuide({ steps }) {
    return (
        <section
            id="setup"
            className="px-6 py-12 border-b border-[var(--border)]"
            data-testid="section-setup"
        >
            <div className="max-w-[1400px] mx-auto">
                <div className="mb-8 flex items-end justify-between flex-wrap gap-4">
                    <div>
                        <div className="kicker mb-2">SECTION 07 / SETUP</div>
                        <h2 className="font-display text-3xl md:text-4xl font-black tracking-tight">
                            Stack: WSL · MT5 · Claude
                            <span className="text-[var(--green)]">.</span>
                        </h2>
                        <p className="mt-3 text-[var(--text-dim)] max-w-[760px] leading-relaxed">
                            9 pasos para llegar de cero a la primera operación
                            asistida. Sigue el orden. <span className="text-[var(--amber)]">Demo durante 2 semanas mínimo</span> antes de tocar la cuenta real.
                        </p>
                    </div>
                    <div className="font-mono text-[11px] text-[var(--text-dim)] hidden md:block">
                        <div>tiempo estimado total: ~3-4h</div>
                        <div>requiere: licencia Claude Pro Max</div>
                    </div>
                </div>

                <div className="space-y-3">
                    {steps.map((s) => (
                        <div
                            key={s.step}
                            className="panel"
                            data-testid={`setup-step-${s.step}`}
                        >
                            <div className="px-5 py-3 border-b border-[var(--border)] flex items-center gap-4">
                                <div className="font-mono text-2xl font-bold text-[var(--green-bright)] tabular w-12">
                                    {String(s.step).padStart(2, "0")}
                                </div>
                                <h3 className="font-display text-lg font-bold tracking-tight">
                                    {s.title}
                                </h3>
                            </div>
                            <pre className="codeblock border-0">
                                {s.commands.join("\n")}
                            </pre>
                        </div>
                    ))}
                </div>

                <div className="panel mt-3 p-5 stripes-warn">
                    <div className="kicker text-[var(--amber)] mb-2">
                        // CHECKLIST DE MIGRACIÓN A REAL
                    </div>
                    <ul className="space-y-1.5 text-[13px]">
                        <li>
                            <span className="font-mono text-[var(--amber)]">›</span>{" "}
                            ≥ 40 trades demo documentados
                        </li>
                        <li>
                            <span className="font-mono text-[var(--amber)]">›</span>{" "}
                            Expectancy {"> +0.30R"} sobre los últimos 30 trades
                        </li>
                        <li>
                            <span className="font-mono text-[var(--amber)]">›</span>{" "}
                            Cero violaciones de reglas en 2 semanas seguidas
                        </li>
                        <li>
                            <span className="font-mono text-[var(--amber)]">›</span>{" "}
                            Empezar real con 0.5% de riesgo, no 1%, durante 7
                            días
                        </li>
                        <li>
                            <span className="font-mono text-[var(--amber)]">›</span>{" "}
                            Te sientes ABURRIDO ejecutando (señal de proceso
                            interiorizado)
                        </li>
                    </ul>
                </div>
            </div>
        </section>
    );
}
