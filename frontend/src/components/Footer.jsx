// Footer — disclaimer mínimo de riesgo + links a documentos legales.
// Visible en todas las rutas del shell. Cumple con el requerimiento de
// que cualquier servicio que opere derivados muestre un aviso de
// pérdida de capital en el área principal de uso.

import { Link } from "react-router-dom";

export default function Footer() {
    return (
        <footer
            className="border-t border-[var(--border)] mt-8 px-6 py-5 text-[11px] text-[var(--text-dim)]"
            data-testid="app-footer"
        >
            <div className="max-w-5xl mx-auto flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                <p className="leading-relaxed">
                    <strong>Aviso de riesgo:</strong> el trading apalancado puede
                    resultar en la pérdida total de tu capital. Resultados pasados
                    no garantizan resultados futuros. Operás bajo tu propia
                    responsabilidad —{" "}
                    <Link to="/legal/risk-disclaimer" className="underline hover:text-[var(--text)]">
                        leé el aviso completo
                    </Link>
                    .
                </p>
                <nav className="flex gap-3">
                    <Link to="/legal/risk-disclaimer" className="hover:text-[var(--text)]">
                        Riesgo
                    </Link>
                    <Link to="/legal/tos" className="hover:text-[var(--text)]">
                        Términos
                    </Link>
                    <Link to="/legal/privacy" className="hover:text-[var(--text)]">
                        Privacidad
                    </Link>
                </nav>
            </div>
        </footer>
    );
}
