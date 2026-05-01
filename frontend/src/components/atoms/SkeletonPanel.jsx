// SkeletonPanel — placeholder de loading. Reemplaza los "Cargando…" pelados.

export default function SkeletonPanel({ rows = 3, height = 16, className = "" }) {
    return (
        <div className={`panel p-5 space-y-3 ${className}`} data-testid="skeleton-panel">
            <div
                className="skeleton"
                style={{ height: 14, width: "30%" }}
            />
            {Array.from({ length: rows }).map((_, i) => (
                <div
                    key={i}
                    className="skeleton"
                    style={{ height, width: i === rows - 1 ? "70%" : "100%" }}
                />
            ))}
        </div>
    );
}

// Variante inline — útil dentro de cards existentes
export function SkeletonLine({ width = "100%", height = 14 }) {
    return (
        <div
            className="skeleton"
            style={{ width, height }}
            data-testid="skeleton-line"
        />
    );
}
