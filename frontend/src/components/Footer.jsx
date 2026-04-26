export default function Footer({ api }) {
    return (
        <footer
            className="border-t border-[var(--border)] px-6 py-6 mt-8"
            data-testid="footer"
        >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div>
                    <div className="kicker mb-2">// DISCLAIMER</div>
                    <p className="text-[12px] text-[var(--text-dim)] leading-relaxed">
                        Esta plataforma es un sistema de planeación y disciplina,
                        NO un consejo financiero. El trading de futuros con
                        apalancamiento puede resultar en pérdidas superiores al
                        capital invertido. Tu cuenta de $800 es 100% riesgo.
                        Sigue las reglas o cierra el bróker.
                    </p>
                </div>
                <div>
                    <div className="kicker mb-2">// API</div>
                    <p className="text-[12px] font-mono text-[var(--text-dim)] break-all">
                        {api}
                    </p>
                </div>
                <div>
                    <div className="kicker mb-2">// VERSION</div>
                    <p className="text-[12px] font-mono text-[var(--text-dim)]">
                        v1.0 — built {new Date().toISOString().slice(0, 10)}
                    </p>
                    <p className="text-[12px] font-mono text-[var(--text-faint)] mt-1">
                        Stack: WSL · MT5 · Claude Pro Max · 4 MCPs
                    </p>
                </div>
            </div>
        </footer>
    );
}
