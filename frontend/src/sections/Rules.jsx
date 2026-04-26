const SEVERITY = {
    critical: {
        label: "CRITICAL",
        bg: "stripes-danger",
        fg: "text-[var(--red)]",
        bar: "bg-[var(--red)]",
    },
    high: {
        label: "HIGH",
        bg: "stripes-warn",
        fg: "text-[var(--amber)]",
        bar: "bg-[var(--amber)]",
    },
    medium: {
        label: "MEDIUM",
        bg: "",
        fg: "text-[var(--blue)]",
        bar: "bg-[var(--blue)]",
    },
};

export default function Rules({ rules }) {
    const grouped = rules.reduce((acc, r) => {
        if (!acc[r.category]) acc[r.category] = [];
        acc[r.category].push(r);
        return acc;
    }, {});

    return (
        <section
            id="rules"
            className="px-6 py-12 border-b border-[var(--border)]"
            data-testid="section-rules"
        >
            <div className="max-w-[1400px] mx-auto">
                <div className="mb-8 flex items-end justify-between flex-wrap gap-4">
                    <div>
                        <div className="kicker mb-2">
                            SECTION 03 / STRICT RULES
                        </div>
                        <h2 className="font-display text-3xl md:text-4xl font-black tracking-tight">
                            Reglas no negociables
                            <span className="text-[var(--red)]">.</span>
                        </h2>
                        <p className="mt-3 text-[var(--text-dim)] max-w-[760px] leading-relaxed">
                            Las reglas no son sugerencias. Si te las saltas, la
                            cuenta de $800 se va a cero como las anteriores. Estas
                            están hardcodeadas en el MCP de risk + trading. La
                            disciplina aquí es lo único que separa a un trader de
                            un apostador.
                        </p>
                    </div>
                    <div className="font-mono text-[11px] text-[var(--text-dim)] hidden md:block">
                        <div className="text-[var(--red)]">
                            critical: 9 ·{" "}
                        </div>
                        <div className="text-[var(--amber)]">high: 9</div>
                        <div className="text-[var(--blue)]">medium: 2</div>
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {Object.entries(grouped).map(([cat, items]) => (
                        <div
                            key={cat}
                            className="panel"
                            data-testid={`rules-group-${cat.toLowerCase()}`}
                        >
                            <div className="px-4 py-3 border-b border-[var(--border)] flex items-center justify-between">
                                <h3 className="font-display font-bold tracking-tight">
                                    {cat}
                                </h3>
                                <span className="kicker">
                                    {items.length} reglas
                                </span>
                            </div>
                            <div>
                                {items.map((r) => {
                                    const sev =
                                        SEVERITY[r.severity] ||
                                        SEVERITY.medium;
                                    return (
                                        <div
                                            key={r.id}
                                            className={`px-4 py-3 border-b border-[var(--border)] last:border-b-0 flex gap-3 items-start ${sev.bg}`}
                                            data-testid={`rule-${r.id}`}
                                        >
                                            <span
                                                className={`w-1 self-stretch ${sev.bar}`}
                                            />
                                            <div className="flex-1">
                                                <div className="flex items-center gap-2 mb-0.5">
                                                    <span
                                                        className={`kicker ${sev.fg}`}
                                                    >
                                                        {sev.label}
                                                    </span>
                                                    <span className="kicker text-[var(--text-faint)]">
                                                        // {r.id}
                                                    </span>
                                                </div>
                                                <div className="text-[13px] leading-relaxed">
                                                    {r.rule}
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}
