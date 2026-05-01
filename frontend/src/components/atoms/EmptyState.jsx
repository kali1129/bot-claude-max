// EmptyState — estado vacío reusable.
// Icono lucide grande, título, body, CTA opcional.

export default function EmptyState({
    icon = null,
    title,
    body,
    cta,
    onCtaClick,
    ctaHref,
    className = "",
}) {
    return (
        <div
            className={`panel p-8 text-center flex flex-col items-center justify-center gap-3 ${className}`}
            data-testid="empty-state"
        >
            {icon ? (
                <div className="text-[var(--text-faint)] mb-2">
                    {icon}
                </div>
            ) : null}
            {title ? (
                <h3 className="font-display text-lg font-bold">{title}</h3>
            ) : null}
            {body ? (
                <p className="text-sm text-[var(--text-dim)] max-w-md">{body}</p>
            ) : null}
            {cta ? (
                ctaHref ? (
                    <a
                        href={ctaHref}
                        className="btn-sharp primary mt-2"
                        data-testid="empty-state-cta"
                    >
                        {cta}
                    </a>
                ) : (
                    <button
                        type="button"
                        onClick={onCtaClick}
                        className="btn-sharp primary mt-2"
                        data-testid="empty-state-cta"
                    >
                        {cta}
                    </button>
                )
            ) : null}
        </div>
    );
}
