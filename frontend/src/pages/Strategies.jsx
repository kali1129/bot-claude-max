// Strategies page — wrapper de Strategies section. En novato simplifica:
// oculta params crudos, banner explicativo "¿Cuál elegir?".

import { useSettings } from "@/lib/userMode";
import { useAuth } from "@/lib/AuthProvider";
import { API_BASE } from "@/lib/api";

import SectionHeader from "@/components/atoms/SectionHeader";
import StrategiesSection from "@/sections/Strategies";

export default function StrategiesPage() {
    const { isNovato } = useSettings();
    const { isAdmin } = useAuth();

    return (
        <section className="px-6 lg:px-10 py-8" data-testid="page-strategies">
            <div className="max-w-[1400px] mx-auto">
                <SectionHeader
                    code="05 / ESTRATEGIAS"
                    title="Estrategias del Bot"
                    subtitle={
                        isNovato
                            ? "Estilos de trading que el bot puede usar. Activá los que querés que esté escaneando."
                            : "Motor multi-estrategia. Cada estrategia tiene parámetros, schedule y edge histórico."
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
                                Si recién empezás, dejá las estrategias activadas como
                                vienen por defecto. El bot ya está calibrado para que
                                funcionen juntas. Más adelante, cuando entiendas cómo
                                opera cada una, podés desactivar las que no te gusten.
                            </p>
                        </div>
                    </div>
                ) : null}

                <StrategiesSection
                    api={API_BASE}
                    novato={isNovato}
                    readOnly={!isAdmin}
                />
            </div>
        </section>
    );
}
