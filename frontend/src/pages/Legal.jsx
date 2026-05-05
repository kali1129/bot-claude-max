// Legal — render simple de los documentos /api/legal/{slug}.
// Sin auth: cualquiera puede leer.

import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";

const VALID_SLUGS = ["risk-disclaimer", "tos", "privacy"];

export default function Legal() {
    const { slug = "risk-disclaimer" } = useParams();
    const [doc, setDoc] = useState(null);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!VALID_SLUGS.includes(slug)) {
            setError(`Documento "${slug}" no existe.`);
            return;
        }
        setDoc(null);
        setError(null);
        fetch(`/api/legal/${slug}`)
            .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
            .then((d) => setDoc(d))
            .catch((e) => setError(String(e)));
    }, [slug]);

    return (
        <div className="min-h-screen bg-[var(--bg)] text-[var(--text)] p-6 lg:p-12">
            <div className="max-w-3xl mx-auto">
                <Link
                    to="/"
                    className="text-xs text-[var(--text-dim)] hover:text-[var(--text)]"
                >
                    ← volver al panel
                </Link>

                {error && (
                    <div className="mt-6 panel p-6 border-red-500/50">
                        <p className="text-red-400">{error}</p>
                    </div>
                )}

                {doc && (
                    <article className="mt-6 prose prose-invert max-w-none">
                        <header className="mb-6">
                            <h1 className="font-display text-3xl font-black mb-1">
                                {doc.title}
                            </h1>
                            <p className="text-xs text-[var(--text-dim)]">
                                Versión {doc.version}
                            </p>
                        </header>
                        <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
                            {doc.markdown}
                        </pre>
                    </article>
                )}

                <nav className="mt-10 pt-6 border-t border-[var(--border)] flex gap-4 text-xs">
                    {VALID_SLUGS.map((s) => (
                        <Link
                            key={s}
                            to={`/legal/${s}`}
                            className={
                                s === slug
                                    ? "text-[var(--text)] font-bold"
                                    : "text-[var(--text-dim)] hover:text-[var(--text)]"
                            }
                        >
                            {s === "risk-disclaimer"
                                ? "Aviso de Riesgo"
                                : s === "tos"
                                  ? "Términos"
                                  : "Privacidad"}
                        </Link>
                    ))}
                </nav>
            </div>
        </div>
    );
}
