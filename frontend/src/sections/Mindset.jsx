export default function Mindset({ principles }) {
    return (
        <section
            id="mindset"
            className="px-6 py-12 border-b border-[var(--border)]"
            data-testid="section-mindset"
        >
            <div className="max-w-[1400px] mx-auto">
                <div className="mb-8">
                    <div className="kicker mb-2">SECTION 08 / MINDSET</div>
                    <h2 className="font-display text-3xl md:text-4xl font-black tracking-tight">
                        Lo psicológico
                        <span className="text-[var(--green)]">.</span>
                    </h2>
                    <p className="mt-3 text-[var(--text-dim)] max-w-[760px] leading-relaxed">
                        Has perdido miles antes. Eso fue el precio del aprendizaje.
                        Los $800 no son para 'recuperar', son para EJECUTAR un
                        sistema con disciplina. Recuperar es consecuencia, no
                        objetivo.
                    </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {principles.map((p, i) => (
                        <div
                            key={i}
                            className="panel p-5"
                            data-testid={`mindset-principle-${i}`}
                        >
                            <div className="flex items-start gap-3">
                                <div className="font-mono text-3xl font-bold text-[var(--green-bright)] tabular leading-none">
                                    {String(i + 1).padStart(2, "0")}
                                </div>
                                <div className="flex-1">
                                    <h3 className="font-display text-lg font-bold tracking-tight mb-2">
                                        {p.title}
                                    </h3>
                                    <p className="text-[13px] text-[var(--text-dim)] leading-relaxed">
                                        {p.body}
                                    </p>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>

                {/* Big closing line */}
                <div className="panel mt-6 p-8 text-center">
                    <p className="font-display text-2xl md:text-3xl font-bold tracking-tight max-w-[800px] mx-auto leading-tight">
                        El edge no está en la estrategia.
                        <br />
                        <span className="text-[var(--green-bright)]">
                            Está en la disciplina.
                        </span>
                    </p>
                    <p className="kicker mt-4">
                        // 1% diario compuesto · 250 días · $800 → $10,000+
                    </p>
                </div>
            </div>
        </section>
    );
}
