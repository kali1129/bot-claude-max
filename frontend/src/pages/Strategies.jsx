// Strategies page — wrapper de Strategies section.
// v3.2: cualquier user logueado puede modificar SU config (mode + min_score).
// Anónimos: solo lectura.

import { useSettings } from "@/lib/userMode";
import { useAuth } from "@/lib/AuthProvider";

import SectionHeader from "@/components/atoms/SectionHeader";
import StrategiesSection from "@/sections/Strategies";

export default function StrategiesPage() {
    const { isNovato } = useSettings();
    const { isAuthenticated, isAdmin } = useAuth();

    return (
        <section className="px-6 lg:px-10 py-8" data-testid="page-strategies">
            <div className="max-w-[1400px] mx-auto">
                <SectionHeader
                    code="05 / ESTRATEGIAS"
                    title="Estrategias del Bot"
                    subtitle={
                        isAdmin
                            ? "Bot global del admin. Cambios afectan al systemd service."
                            : isAuthenticated
                            ? "Tu config personal. Cambios afectan a tu bot (no al de otros)."
                            : "Motor multi-estrategia. Iniciá sesión para personalizar tu config."
                    }
                />

                {isNovato ? (
                    <div
                        className="panel mb-4 p-4 stripes-warn flex items-start gap-3"
                        style={{ borderColor: "var(--novato-accent)" }}
                    >
                        <div className="text-[var(--novato-accent)] text-xl flex-shrink-0">
                            💡
                        </div>
                        <div>
                            <div className="font-display text-sm font-bold mb-1">
                                ¿Cuál elegir?
                            </div>
                            <p className="text-xs text-[var(--text-dim)] leading-relaxed">
                                Si recién empezás, usá <strong>AUTO</strong> (recomendado) y
                                dejá el score mínimo en <strong>70</strong>. El bot va a
                                evaluar todas las estrategias y operar la mejor señal de
                                cada par automáticamente.
                            </p>
                        </div>
                    </div>
                ) : null}

                <StrategiesSection
                    novato={isNovato}
                    readOnly={!isAuthenticated}
                />
            </div>
        </section>
    );
}
