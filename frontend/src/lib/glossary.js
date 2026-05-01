// Diccionario centralizado novato↔experto.
// Usado por <NovatoTooltip term="..."> y por copy condicional.

export const GLOSSARY = {
    atr: {
        label: "Volatilidad reciente",
        body: "Qué tan movido está el mercado ahora. A más volatilidad, más amplios los stops.",
    },
    rr: {
        label: "Riesgo / Recompensa",
        body: "Por cada $1 que arriesgás, cuánto buscás ganar. 1:2 = ganás $2 por cada $1 de riesgo.",
    },
    drawdown: {
        label: "Caída desde el máximo",
        body: "Cuánto bajó tu cuenta desde el mejor momento histórico.",
    },
    max_drawdown: {
        label: "Peor caída histórica",
        body: "La mayor caída sostenida que tuvo tu cuenta. Si entra a un nuevo peor, se actualiza.",
    },
    expectancy: {
        label: "Ganancia promedio por operación",
        body: "Cuánto ganás (o perdés) en promedio cada vez. Suma todo, divide por número de trades.",
    },
    win_rate: {
        label: "% de operaciones ganadoras",
        body: "De cada 10 operaciones, cuántas terminan en verde.",
    },
    equity: {
        label: "Saldo actual de la cuenta",
        body: "Incluye lo que vale tu posición abierta ahora mismo.",
    },
    balance: {
        label: "Saldo cerrado",
        body: "Saldo sin contar lo que tenés abierto. Solo lo ya realizado.",
    },
    lot: {
        label: "Tamaño de la operación",
        body: "Cuánto comprás/vendés. 0.01 es chico, 0.1 mediano, 1.0 grande.",
    },
    pip: {
        label: "Movimiento mínimo del precio",
        body: "La unidad más chica que se mueve un par de divisas.",
    },
    sl: {
        label: "Tope de pérdida",
        body: "Si el precio llega aquí, el bot cierra automáticamente para limitar la pérdida.",
    },
    tp: {
        label: "Objetivo de ganancia",
        body: "Si el precio llega aquí, el bot cierra y se queda con la ganancia.",
    },
    break_even: {
        label: "Empate (sin perder ni ganar)",
        body: "Operación cerrada al precio de entrada.",
    },
    halt: {
        label: "Parada de emergencia",
        body: "Cierra todo y desactiva el bot inmediatamente.",
    },
    discipline: {
        label: "Disciplina del bot",
        body: "Qué tan bien siguió las reglas en las últimas operaciones.",
    },
    edge: {
        label: "Ventaja estadística",
        body: "Si la combinación de estrategia y símbolo gana plata en el largo plazo.",
    },
    spread: {
        label: "Costo del broker por operación",
        body: "Diferencia entre precio compra y venta. Lo cobra el broker.",
    },
    sharpe: {
        label: "Sharpe Ratio",
        body: "Métrica avanzada de rentabilidad ajustada por riesgo. Solo útil para experimentados.",
    },
    sortino: {
        label: "Sortino Ratio",
        body: "Variante del Sharpe que penaliza solo volatilidad negativa.",
    },
    sqn: {
        label: "SQN (Van Tharp)",
        body: "System Quality Number. Mide qué tan bueno es el sistema.",
    },
    profit_factor: {
        label: "Profit Factor",
        body: "Ganancias totales / Pérdidas totales. > 1 = sistema rentable.",
    },
    calmar: {
        label: "Calmar Ratio",
        body: "Retorno anualizado / Max Drawdown. Mide return vs riesgo de drawdown.",
    },
    kelly: {
        label: "Kelly Fraction",
        body: "Tamaño óptimo de la apuesta según teoría de Kelly. Usar con cuidado.",
    },
    magic_id: {
        label: "Magic ID",
        body: "Identificador del bot para distinguir sus trades de los manuales.",
    },
};

// Convierte un término técnico a etiqueta amigable según modo.
export function friendlyLabel(term, mode) {
    const entry = GLOSSARY[term?.toLowerCase?.()];
    if (!entry) return term;
    if (mode === "experto") return term;
    return entry.label;
}

// Mapea valor crudo de lots a etiqueta S/M/L para novato.
export function lotsToSize(lots) {
    if (lots == null || !Number.isFinite(Number(lots))) return "—";
    const n = Number(lots);
    if (n <= 0.05) return "Chico";
    if (n <= 0.5) return "Mediano";
    return "Grande";
}
