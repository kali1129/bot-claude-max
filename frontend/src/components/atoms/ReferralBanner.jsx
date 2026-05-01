// ReferralBanner — banner para promover XM (link de afiliados).
// Variantes:
//   · "compact" — línea horizontal discreta para sidebar/footer
//   · "feature" — card grande con CTA verde para /ayuda y onboarding step 5

import { ExternalLink, Gift } from "lucide-react";
import { useSettings } from "@/lib/userMode";

export default function ReferralBanner({ variant = "compact", url, label }) {
    const { settings } = useSettings();
    const partner = settings?.referral_partner || {};
    const finalUrl = url || partner.url || "https://www.xm.com/";
    const finalLabel = label || partner.label || "XM Global";

    if (variant === "feature") {
        return (
            <div
                className="panel p-6 stripes-warn relative overflow-hidden"
                data-testid="referral-banner-feature"
                style={{ borderColor: "var(--green)" }}
            >
                <div className="flex items-start gap-4 flex-wrap">
                    <div
                        className="flex items-center justify-center w-12 h-12 flex-shrink-0"
                        style={{ background: "var(--green-bright)", color: "#000" }}
                    >
                        <Gift size={20} />
                    </div>
                    <div className="flex-1 min-w-[200px]">
                        <div className="kicker mb-1 text-[var(--green-bright)]">
                            BROKER RECOMENDADO
                        </div>
                        <h3 className="font-display text-lg md:text-xl font-bold mb-2">
                            ¿Aún no tenés cuenta de trading?
                        </h3>
                        <p className="text-sm text-[var(--text-dim)] leading-relaxed">
                            Abrí una con {finalLabel} en 2 minutos. Es gratis y al hacerlo
                            por este link nos ayudás a mantener este bot funcionando.
                        </p>
                    </div>
                    <a
                        href={finalUrl}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="btn-sharp primary btn-xl flex items-center gap-2"
                        data-testid="referral-cta"
                    >
                        Abrir cuenta {finalLabel}
                        <ExternalLink size={14} />
                    </a>
                </div>
            </div>
        );
    }

    // compact
    return (
        <a
            href={finalUrl}
            target="_blank"
            rel="noreferrer noopener"
            className="flex items-center justify-between gap-2 px-4 py-2 panel hover:border-[var(--border-strong)] transition-colors"
            data-testid="referral-banner-compact"
        >
            <div className="flex items-center gap-2 min-w-0">
                <Gift size={12} className="text-[var(--green)] flex-shrink-0" />
                <span className="text-xs font-mono text-[var(--text-dim)] truncate">
                    Abrí cuenta {finalLabel}
                </span>
            </div>
            <ExternalLink size={11} className="text-[var(--text-faint)] flex-shrink-0" />
        </a>
    );
}
