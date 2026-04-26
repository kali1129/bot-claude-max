import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
    BookText,
    Newspaper,
    TrendingUp,
    LineChart,
    ShieldAlert,
    LayoutDashboard,
    Wrench,
    ArrowDownToLine,
    Eye,
    EyeOff,
    FileCode,
} from "lucide-react";
import { toast } from "sonner";

const ICON_BY_ID = {
    "00-overview": BookText,
    "01-mcp-news": Newspaper,
    "02-mcp-trading": TrendingUp,
    "03-mcp-analysis": LineChart,
    "04-mcp-risk": ShieldAlert,
    "05-dashboard": LayoutDashboard,
    "06-setup": Wrench,
};

const COLOR_BY_KIND = {
    overview: "text-[var(--text)]",
    mcp: "text-[var(--green-bright)]",
    system: "text-[var(--blue)]",
    guide: "text-[var(--amber)]",
};

const BORDER_BY_KIND = {
    overview: "border-[var(--border-strong)]",
    mcp: "border-[var(--green)]",
    system: "border-[var(--blue)]",
    guide: "border-[var(--amber)]",
};

function fmtKB(bytes) {
    if (!bytes) return "—";
    return `${(bytes / 1024).toFixed(1)} KB`;
}

export default function ArchitectureDocs({ api }) {
    const [docs, setDocs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [activeDocId, setActiveDocId] = useState(null);
    const [activeContent, setActiveContent] = useState("");
    const [contentLoading, setContentLoading] = useState(false);

    const fetchList = useCallback(async () => {
        try {
            const res = await axios.get(`${api}/docs`);
            setDocs(res.data.docs || []);
        } catch (e) {
            toast.error("Error cargando docs");
        } finally {
            setLoading(false);
        }
    }, [api]);

    useEffect(() => {
        fetchList();
    }, [fetchList]);

    const view = async (docId) => {
        if (activeDocId === docId) {
            setActiveDocId(null);
            setActiveContent("");
            return;
        }
        setContentLoading(true);
        setActiveDocId(docId);
        try {
            const res = await axios.get(`${api}/docs/${docId}`);
            setActiveContent(res.data);
        } catch (e) {
            toast.error("Error cargando contenido");
            setActiveContent("");
        } finally {
            setContentLoading(false);
        }
    };

    const download = async (doc) => {
        try {
            const res = await axios.get(`${api}/docs/${doc.id}`);
            const blob = new Blob([res.data], { type: "text/markdown" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = doc.file;
            a.click();
            URL.revokeObjectURL(url);
            toast.success(`${doc.file} descargado`);
        } catch (e) {
            toast.error("Error descargando");
        }
    };

    const downloadAll = async () => {
        for (const d of docs) {
            try {
                const res = await axios.get(`${api}/docs/${d.id}`);
                const blob = new Blob([res.data], { type: "text/markdown" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = d.file;
                a.click();
                URL.revokeObjectURL(url);
                await new Promise((r) => setTimeout(r, 250));
            } catch (e) {
                /* ignore */
            }
        }
        toast.success(`${docs.length} archivos descargados`);
    };

    return (
        <section
            id="architecture-docs"
            className="px-6 py-12 border-b border-[var(--border)]"
            data-testid="section-arch-docs"
        >
            <div className="max-w-[1400px] mx-auto">
                <div className="mb-8 flex items-end justify-between flex-wrap gap-4">
                    <div>
                        <div className="kicker mb-2">
                            SECTION 09 / ARCHITECTURE DOCS
                        </div>
                        <h2 className="font-display text-3xl md:text-4xl font-black tracking-tight">
                            READMEs por componente
                            <span className="text-[var(--green)]">.</span>
                        </h2>
                        <p className="mt-3 text-[var(--text-dim)] max-w-[760px] leading-relaxed">
                            Documentación detallada de cada parte de la
                            arquitectura: 1 overview general, 4 MCPs, dashboard
                            web y setup completo paso a paso. Cada README es
                            independiente, autocontenido y puedes descargarlo
                            para tener offline.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={downloadAll}
                        className="btn-sharp primary"
                        data-testid="download-all-docs-btn"
                    >
                        <ArrowDownToLine size={12} className="inline mr-1" />
                        Descargar todos (.md)
                    </button>
                </div>

                {loading ? (
                    <div className="kicker">// LOADING DOCS…</div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {docs.map((d) => {
                            const Icon = ICON_BY_ID[d.id] || FileCode;
                            const isActive = activeDocId === d.id;
                            return (
                                <div
                                    key={d.id}
                                    className="panel"
                                    data-testid={`doc-card-${d.id}`}
                                >
                                    <div
                                        className={`p-5 border-b border-[var(--border)] flex items-start gap-4`}
                                    >
                                        <div
                                            className={`p-2 border ${BORDER_BY_KIND[d.kind]}`}
                                        >
                                            <Icon
                                                size={20}
                                                className={
                                                    COLOR_BY_KIND[d.kind]
                                                }
                                                strokeWidth={1.5}
                                            />
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="kicker mb-1 flex items-center gap-2">
                                                <span>
                                                    DOC_
                                                    {String(d.order).padStart(
                                                        2,
                                                        "0"
                                                    )}
                                                </span>
                                                <span className="text-[var(--text-faint)]">
                                                    · {d.kind}
                                                </span>
                                            </div>
                                            <h3 className="font-display text-base font-bold tracking-tight leading-tight">
                                                {d.title}
                                            </h3>
                                            <div className="kicker mt-1 normal-case tracking-normal text-[var(--text-faint)]">
                                                {d.file} · {fmtKB(d.size_bytes)}
                                            </div>
                                        </div>
                                    </div>

                                    <div className="p-3 flex items-center gap-2">
                                        <button
                                            type="button"
                                            onClick={() => view(d.id)}
                                            className="btn-sharp flex-1"
                                            data-testid={`view-doc-${d.id}`}
                                        >
                                            {isActive ? (
                                                <>
                                                    <EyeOff
                                                        size={12}
                                                        className="inline mr-1"
                                                    />
                                                    Cerrar
                                                </>
                                            ) : (
                                                <>
                                                    <Eye
                                                        size={12}
                                                        className="inline mr-1"
                                                    />
                                                    Ver inline
                                                </>
                                            )}
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => download(d)}
                                            className="btn-sharp primary"
                                            data-testid={`download-doc-${d.id}`}
                                            title="Descargar .md"
                                        >
                                            <ArrowDownToLine size={12} />
                                        </button>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}

                {/* Inline viewer */}
                {activeDocId && (
                    <div
                        className="panel mt-3"
                        data-testid={`doc-viewer-${activeDocId}`}
                    >
                        <div className="px-5 py-3 border-b border-[var(--border)] flex items-center justify-between">
                            <div className="kicker">
                                // {docs.find((d) => d.id === activeDocId)?.file}
                            </div>
                            <button
                                type="button"
                                onClick={() => view(activeDocId)}
                                className="btn-sharp"
                                data-testid="close-viewer"
                            >
                                <EyeOff size={12} className="inline mr-1" /> Cerrar
                            </button>
                        </div>
                        <div className="p-5 max-h-[640px] overflow-y-auto">
                            {contentLoading ? (
                                <div className="kicker">// LOADING…</div>
                            ) : (
                                <pre
                                    className="codeblock"
                                    style={{ maxHeight: "none" }}
                                >
                                    {activeContent}
                                </pre>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </section>
    );
}
