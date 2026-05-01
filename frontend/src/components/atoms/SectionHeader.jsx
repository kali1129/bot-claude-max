// SectionHeader — header consistente para cada page.
// kicker (SECCIÓN XX) + h2 + sublabel + action button derecha.

export default function SectionHeader({
    code,
    title,
    subtitle,
    action,
    className = "",
}) {
    return (
        <div
            className={`flex items-end justify-between mb-6 gap-4 flex-wrap ${className}`}
            data-testid="section-header"
        >
            <div className="min-w-0">
                {code ? (
                    <div className="kicker mb-2">
                        SECCIÓN {code}
                    </div>
                ) : null}
                <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight">
                    {title}
                </h1>
                {subtitle ? (
                    <p className="mt-2 text-[var(--text-dim)] max-w-[640px] text-sm leading-relaxed">
                        {subtitle}
                    </p>
                ) : null}
            </div>
            {action ? <div className="flex-shrink-0">{action}</div> : null}
        </div>
    );
}
