import { useState } from "react";
import axios from "axios";
import { Calculator, AlertTriangle } from "lucide-react";

const PRESETS = {
    "EURUSD (Forex Major)": {
        pip_size: 0.0001,
        pip_value: 10,
        lot_step: 0.01,
        max_lot: 0.5,
    },
    "USDJPY (JPY pair)": {
        pip_size: 0.01,
        pip_value: 9.5,
        lot_step: 0.01,
        max_lot: 0.5,
    },
    "XAUUSD (Oro)": {
        pip_size: 0.1,
        pip_value: 1,
        lot_step: 0.01,
        max_lot: 0.5,
    },
    "NAS100 (Índice)": {
        pip_size: 1.0,
        pip_value: 1,
        lot_step: 0.1,
        max_lot: 2,
    },
    "BTCUSD (Cripto)": {
        pip_size: 1.0,
        pip_value: 0.01,
        lot_step: 0.01,
        max_lot: 0.5,
    },
};

export default function RiskCalculator({ api, defaultBalance }) {
    const [preset, setPreset] = useState("EURUSD (Forex Major)");
    const [balance, setBalance] = useState(defaultBalance);
    const [riskPct, setRiskPct] = useState(1);
    const [entry, setEntry] = useState(1.0850);
    const [sl, setSl] = useState(1.0830);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(false);

    const calc = async () => {
        setLoading(true);
        setError(null);
        const cfg = PRESETS[preset];
        try {
            const res = await axios.post(`${api}/risk/calc`, {
                balance: parseFloat(balance),
                risk_pct: parseFloat(riskPct),
                entry: parseFloat(entry),
                stop_loss: parseFloat(sl),
                pip_value: cfg.pip_value,
                pip_size: cfg.pip_size,
                lot_step: cfg.lot_step,
                min_lot: 0.01,
                max_lot: cfg.max_lot,
            });
            setResult(res.data);
        } catch (e) {
            setError(e.response?.data?.detail || "Error en el cálculo");
            setResult(null);
        } finally {
            setLoading(false);
        }
    };

    const Field = ({ label, children }) => (
        <div>
            <div className="kicker mb-1.5">{label}</div>
            {children}
        </div>
    );

    return (
        <section
            id="risk-calc"
            className="px-6 py-12 border-b border-[var(--border)]"
            data-testid="section-risk-calc"
        >
            <div className="max-w-[1400px] mx-auto">
                <div className="mb-8">
                    <div className="kicker mb-2">SECTION 05 / RISK CALC</div>
                    <h2 className="font-display text-3xl md:text-4xl font-black tracking-tight">
                        Position size calculator
                        <span className="text-[var(--green)]">.</span>
                    </h2>
                    <p className="mt-3 text-[var(--text-dim)] max-w-[760px] leading-relaxed">
                        Antes de cada trade: balance × riesgo% / (distancia SL ×
                        valor pip) = lotaje exacto. Si calculas a ojo, pierdes a
                        ojo.
                    </p>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                    {/* Input panel */}
                    <div className="panel p-5">
                        <div className="kicker mb-4">// INPUTS</div>

                        <div className="grid grid-cols-2 gap-3 mb-3">
                            <Field label="Activo (preset)">
                                <select
                                    value={preset}
                                    onChange={(e) => setPreset(e.target.value)}
                                    className="input-sharp"
                                    data-testid="risk-preset"
                                >
                                    {Object.keys(PRESETS).map((k) => (
                                        <option key={k} value={k}>
                                            {k}
                                        </option>
                                    ))}
                                </select>
                            </Field>
                            <Field label="Balance USD">
                                <input
                                    type="number"
                                    value={balance}
                                    onChange={(e) =>
                                        setBalance(e.target.value)
                                    }
                                    className="input-sharp"
                                    data-testid="risk-balance"
                                />
                            </Field>
                            <Field label="Riesgo %">
                                <input
                                    type="number"
                                    step="0.1"
                                    value={riskPct}
                                    onChange={(e) =>
                                        setRiskPct(e.target.value)
                                    }
                                    className="input-sharp"
                                    data-testid="risk-pct"
                                />
                            </Field>
                            <Field label="Entry">
                                <input
                                    type="number"
                                    step="any"
                                    value={entry}
                                    onChange={(e) => setEntry(e.target.value)}
                                    className="input-sharp"
                                    data-testid="risk-entry"
                                />
                            </Field>
                            <Field label="Stop Loss">
                                <input
                                    type="number"
                                    step="any"
                                    value={sl}
                                    onChange={(e) => setSl(e.target.value)}
                                    className="input-sharp"
                                    data-testid="risk-sl"
                                />
                            </Field>
                            <Field label="Pip size · Pip value">
                                <input
                                    readOnly
                                    value={`${PRESETS[preset].pip_size} · $${PRESETS[preset].pip_value}`}
                                    className="input-sharp opacity-70"
                                />
                            </Field>
                        </div>

                        <button
                            type="button"
                            onClick={calc}
                            disabled={loading}
                            className="btn-sharp primary w-full"
                            data-testid="risk-calc-btn"
                        >
                            <Calculator size={12} className="inline mr-1" />
                            {loading ? "CALCULANDO…" : "CALCULAR LOTAJE"}
                        </button>

                        {error && (
                            <div className="mt-3 px-3 py-2 border border-[var(--red)] text-[var(--red)] text-[12px] font-mono stripes-danger">
                                ERROR: {error}
                            </div>
                        )}
                    </div>

                    {/* Result panel */}
                    <div
                        className="panel p-5 flex flex-col"
                        data-testid="risk-result-panel"
                    >
                        <div className="kicker mb-4">// OUTPUT</div>

                        {!result ? (
                            <div className="flex-1 flex items-center justify-center text-[var(--text-faint)] font-mono text-[12px]">
                                Esperando cálculo…
                            </div>
                        ) : (
                            <div className="space-y-4 flex-1">
                                <div className="border border-[var(--green)] p-4 text-center">
                                    <div className="kicker mb-1">LOTAJE</div>
                                    <div
                                        className="font-mono text-5xl font-bold tabular text-[var(--green-bright)]"
                                        data-testid="risk-result-lots"
                                    >
                                        {result.lots}
                                    </div>
                                    <div className="kicker mt-1 normal-case tracking-normal text-[var(--text-dim)]">
                                        envíalo así a place_order(...)
                                    </div>
                                </div>

                                <div className="grid grid-cols-2 gap-2">
                                    <div className="border border-[var(--border)] p-3">
                                        <div className="kicker mb-0.5">
                                            Riesgo $
                                        </div>
                                        <div
                                            className="font-mono text-lg font-semibold tabular"
                                            data-testid="risk-result-dollars"
                                        >
                                            ${result.risk_dollars}
                                        </div>
                                    </div>
                                    <div className="border border-[var(--border)] p-3">
                                        <div className="kicker mb-0.5">
                                            Riesgo % real
                                        </div>
                                        <div className="font-mono text-lg font-semibold tabular">
                                            {result.risk_pct_actual}%
                                        </div>
                                    </div>
                                    <div className="border border-[var(--border)] p-3">
                                        <div className="kicker mb-0.5">
                                            SL distance
                                        </div>
                                        <div className="font-mono text-lg font-semibold tabular">
                                            {result.sl_distance}
                                        </div>
                                    </div>
                                    <div className="border border-[var(--border)] p-3">
                                        <div className="kicker mb-0.5">
                                            SL pips
                                        </div>
                                        <div className="font-mono text-lg font-semibold tabular">
                                            {result.sl_pips}
                                        </div>
                                    </div>
                                </div>

                                {result.warnings && result.warnings.length > 0 && (
                                    <div className="border border-[var(--amber)] p-3 stripes-warn">
                                        <div className="flex items-center gap-2 mb-1">
                                            <AlertTriangle
                                                size={14}
                                                className="text-[var(--amber)]"
                                            />
                                            <span className="kicker text-[var(--amber)]">
                                                AVISOS
                                            </span>
                                        </div>
                                        <ul className="space-y-1">
                                            {result.warnings.map((w, i) => (
                                                <li
                                                    key={i}
                                                    className="text-[12px] text-[var(--text-dim)] font-mono"
                                                    data-testid={`risk-warn-${i}`}
                                                >
                                                    {w}
                                                </li>
                                            ))}
                                        </ul>
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                </div>

                {/* Formula explainer */}
                <div className="panel mt-3 p-5">
                    <div className="kicker mb-3">// FÓRMULA</div>
                    <pre className="codeblock">
{`risk_dollars = balance * (risk_pct / 100)
sl_pips      = abs(entry - stop_loss) / pip_size
lots         = risk_dollars / (sl_pips * pip_value)
lots         = max(min_lot, snap_to(lot_step))
lots         = min(lots, max_lot)   // cap de seguridad`}
                    </pre>
                </div>
            </div>
        </section>
    );
}
