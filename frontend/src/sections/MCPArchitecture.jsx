import { useState } from "react";
import {
    Newspaper,
    TrendingUp,
    LineChart,
    ShieldAlert,
    Copy,
    Check,
} from "lucide-react";
import { toast } from "sonner";

const ICON_MAP = {
    Newspaper,
    TrendingUp,
    LineChart,
    ShieldAlert,
};

const COLOR_MAP = {
    amber: { fg: "text-[var(--amber)]", border: "border-[var(--amber)]" },
    green: { fg: "text-[var(--green-bright)]", border: "border-[var(--green)]" },
    blue: { fg: "text-[var(--blue)]", border: "border-[var(--blue)]" },
    red: { fg: "text-[var(--red)]", border: "border-[var(--red)]" },
};

function MCPCard({ mcp, index }) {
    const Icon = ICON_MAP[mcp.icon] || Newspaper;
    const c = COLOR_MAP[mcp.color] || COLOR_MAP.green;
    const [copied, setCopied] = useState(false);
    const [expanded, setExpanded] = useState(false);

    const copyPrompt = () => {
        navigator.clipboard.writeText(mcp.prompt);
        setCopied(true);
        toast.success(`Prompt de ${mcp.name} copiado`);
        setTimeout(() => setCopied(false), 1800);
    };

    return (
        <div
            className="panel"
            data-testid={`mcp-card-${mcp.id}`}
        >
            <div className={`p-5 border-b border-[var(--border)] flex items-start gap-4`}>
                <div className={`p-2 border ${c.border}`}>
                    <Icon size={20} className={c.fg} strokeWidth={1.5} />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="kicker mb-1">
                        MCP_{String(index + 1).padStart(2, "0")}
                    </div>
                    <h3 className="font-display text-xl font-bold tracking-tight">
                        {mcp.name}
                    </h3>
                </div>
            </div>

            <div className="p-5 space-y-4">
                <p className="text-[13px] text-[var(--text-dim)] leading-relaxed">
                    {mcp.purpose}
                </p>

                <div>
                    <div className="kicker mb-2">// TOOLS EXPUESTAS</div>
                    <ul className="space-y-1">
                        {mcp.tools.map((t, i) => (
                            <li
                                key={i}
                                className="font-mono text-[11.5px] text-[var(--text-dim)] flex gap-2"
                            >
                                <span className={c.fg}>›</span>
                                <span className="break-all">{t}</span>
                            </li>
                        ))}
                    </ul>
                </div>

                {mcp.env_keys.length > 0 && (
                    <div>
                        <div className="kicker mb-2">// ENV REQUIRED</div>
                        <div className="flex flex-wrap gap-2">
                            {mcp.env_keys.map((k, i) => (
                                <span
                                    key={i}
                                    className="font-mono text-[10.5px] px-2 py-1 border border-[var(--border-strong)] text-[var(--amber)]"
                                >
                                    {k}
                                </span>
                            ))}
                        </div>
                    </div>
                )}

                <div className="pt-2 flex items-center gap-2 flex-wrap">
                    <button
                        type="button"
                        onClick={copyPrompt}
                        className="btn-sharp primary"
                        data-testid={`copy-prompt-${mcp.id}`}
                    >
                        {copied ? (
                            <>
                                <Check size={12} className="inline mr-1" /> Copiado
                            </>
                        ) : (
                            <>
                                <Copy size={12} className="inline mr-1" /> Copy Prompt
                            </>
                        )}
                    </button>
                    <button
                        type="button"
                        onClick={() => setExpanded((e) => !e)}
                        className="btn-sharp"
                        data-testid={`toggle-prompt-${mcp.id}`}
                    >
                        {expanded ? "Ocultar prompt" : "Ver prompt"}
                    </button>
                </div>

                {expanded && (
                    <pre
                        className="codeblock max-h-[420px] overflow-y-auto"
                        data-testid={`prompt-block-${mcp.id}`}
                    >
                        {mcp.prompt}
                    </pre>
                )}
            </div>
        </div>
    );
}

export default function MCPArchitecture({ mcps }) {
    return (
        <section
            id="mcps"
            className="px-6 py-12 border-b border-[var(--border)]"
            data-testid="section-mcps"
        >
            <div className="max-w-[1400px] mx-auto">
                <div className="mb-8 flex items-end justify-between flex-wrap gap-4">
                    <div>
                        <div className="kicker mb-2">SECTION 01 / MCP STACK</div>
                        <h2 className="font-display text-3xl md:text-4xl font-black tracking-tight">
                            4 MCPs que te dan superpoderes
                            <span className="text-[var(--green)]">.</span>
                        </h2>
                        <p className="mt-3 text-[var(--text-dim)] max-w-[760px] leading-relaxed">
                            Cada MCP es un servidor Python que corre en tu Windows
                            y se conecta con Claude Desktop. Copia el prompt de
                            cada tarjeta, pégaselo a Claude Code, y él construirá
                            el server completo con sus tools, validaciones y
                            configuración para `claude_desktop_config.json`.
                        </p>
                    </div>
                    <div className="font-mono text-[11px] text-[var(--text-dim)] hidden md:block">
                        <div>news → noticias + calendario</div>
                        <div>trading → ejecución MT5</div>
                        <div>analysis → indicadores + estructura</div>
                        <div>risk → guardian de cuenta</div>
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {mcps.map((m, i) => (
                        <MCPCard key={m.id} mcp={m} index={i} />
                    ))}
                </div>

                {/* Architecture diagram (text) */}
                <div className="panel mt-3 p-5">
                    <div className="kicker mb-3">// FLOW: cómo conversan</div>
                    <pre className="codeblock">
{`     ┌──────────────────┐
     │  Claude Pro Max  │  ← tú das instrucciones
     └────────┬─────────┘
              │ MCP protocol (stdio)
   ┌──────────┼──────────┬─────────────┐
   ▼          ▼          ▼             ▼
 [news]   [analysis]  [trading]    [risk]
   │          │          │             │
   ▼          ▼          ▼             ▼
 ForexFactory  Pure CPU  MT5 Windows   state.json
 NewsAPI                  (real $$)    drawdown lock
 Finnhub

ORDEN DE TRABAJO TÍPICO (cada setup):
  1. risk.daily_status()           ← ¿puedo operar hoy?
  2. news.is_tradeable_now(symbol) ← ¿hay noticia bloqueante?
  3. trading.get_rates(...)        ← traer OHLCV
  4. analysis.score_setup(...)     ← ¿score >= 70?
  5. risk.calc_position_size(...)  ← cuántos lotes
  6. trading.place_order(...)      ← envío con guardas
  7. risk.register_trade(result)   ← actualizar state`}
                    </pre>
                </div>
            </div>
        </section>
    );
}
