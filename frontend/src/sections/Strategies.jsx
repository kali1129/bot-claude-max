const COLOR_DOT = {
    green: "bg-[var(--green)]",
    blue: "bg-[var(--blue)]",
    amber: "bg-[var(--amber)]",
    red: "bg-[var(--red)]",
};

function StratCard({ s, index }) {
    return (
        <div
            className="panel"
            data-testid={`strategy-card-${s.id}`}
        >
            <div className="p-5 border-b border-[var(--border)]">
                <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                            <span
                                className={`w-1.5 h-1.5 ${COLOR_DOT[s.color] || "bg-white"}`}
                            />
                            <span className="kicker">
                                STRAT_{String(index + 1).padStart(2, "0")} /{" "}
                                {s.type}
                            </span>
                        </div>
                        <h3 className="font-display text-xl font-bold tracking-tight">
                            {s.name}
                        </h3>
                    </div>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-[11.5px]">
                    <div>
                        <div className="kicker mb-0.5">R:R</div>
                        <div className="font-mono font-semibold text-[var(--green-bright)]">
                            {s.rr}
                        </div>
                    </div>
                    <div>
                        <div className="kicker mb-0.5">WIN-RATE</div>
                        <div className="font-mono font-semibold">
                            {s.expected_winrate}
                        </div>
                    </div>
                    <div>
                        <div className="kicker mb-0.5">SESIÓN</div>
                        <div className="font-mono font-semibold text-[var(--text-dim)] truncate">
                            {s.session.split(" ").slice(-1)[0]}
                        </div>
                    </div>
                </div>
            </div>

            <div className="p-5 space-y-4">
                <div>
                    <div className="kicker mb-1">// MEJOR PARA</div>
                    <div className="text-[12.5px] text-[var(--text-dim)]">
                        {s.best_for}
                    </div>
                </div>
                <div>
                    <div className="kicker mb-1">// SESIÓN</div>
                    <div className="font-mono text-[12px] text-[var(--text-dim)]">
                        {s.session}
                    </div>
                </div>

                <div>
                    <div className="kicker mb-2">// REGLAS</div>
                    <ol className="space-y-1.5">
                        {s.rules.map((r, i) => (
                            <li
                                key={i}
                                className="text-[12.5px] text-[var(--text-dim)] flex gap-2"
                            >
                                <span className="font-mono text-[var(--green-bright)] flex-shrink-0">
                                    {String(i + 1).padStart(2, "0")}
                                </span>
                                <span>{r}</span>
                            </li>
                        ))}
                    </ol>
                </div>

                <div className="pt-2 border-t border-[var(--border)]">
                    <div className="kicker mb-2">// FILTROS OBLIGATORIOS</div>
                    <ul className="space-y-1">
                        {s.filters.map((f, i) => (
                            <li
                                key={i}
                                className="text-[12px] text-[var(--text-dim)] flex gap-2"
                            >
                                <span className="text-[var(--amber)]">!</span>
                                <span>{f}</span>
                            </li>
                        ))}
                    </ul>
                </div>
            </div>
        </div>
    );
}

export default function Strategies({ strategies }) {
    return (
        <section
            id="strategies"
            className="px-6 py-12 border-b border-[var(--border)]"
            data-testid="section-strategies"
        >
            <div className="max-w-[1400px] mx-auto">
                <div className="mb-8 flex items-end justify-between flex-wrap gap-4">
                    <div>
                        <div className="kicker mb-2">
                            SECTION 02 / STRATEGIES
                        </div>
                        <h2 className="font-display text-3xl md:text-4xl font-black tracking-tight">
                            6 setups validados
                            <span className="text-[var(--green)]">.</span>
                        </h2>
                        <p className="mt-3 text-[var(--text-dim)] max-w-[760px] leading-relaxed">
                            La IA debe escoger el mejor mercado del día y aplicar
                            uno de estos setups. Setups B (no listados aquí) =
                            SKIP. Cada estrategia tiene reglas claras de entrada,
                            stop, target y filtros obligatorios.
                        </p>
                    </div>
                    <div className="font-mono text-[11px] text-[var(--text-dim)] hidden md:block">
                        <div>4 intradía · 1 swing · 1 reactiva</div>
                        <div className="text-[var(--green-bright)]">
                            siempre 1 sola posición abierta
                        </div>
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {strategies.map((s, i) => (
                        <StratCard key={s.id} s={s} index={i} />
                    ))}
                </div>
            </div>
        </section>
    );
}
