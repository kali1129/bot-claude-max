// Live page — wrapper de LiveDashboard section. En novato oculta detalles
// técnicos (ATR, lots raw, Kelly numbers) y muestra copy más accesible.

import { useSettings } from "@/lib/userMode";
import { API_BASE } from "@/lib/api";

import SectionHeader from "@/components/atoms/SectionHeader";
import LiveDashboard from "@/sections/LiveDashboard";

export default function Live() {
    const { isNovato } = useSettings();

    return (
        <div data-testid="page-live">
            {/* El SectionHeader ya viene incluido dentro de LiveDashboard;
                pasamos prop novato para que ajuste su contenido si lo soporta */}
            <LiveDashboard api={API_BASE} novato={isNovato} />
        </div>
    );
}
