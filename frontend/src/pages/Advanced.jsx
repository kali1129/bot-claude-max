// Advanced page (solo experto). Tabs: Backtest · Optimizer · Research Log.
// Walk-forward y Monte Carlo si existen sub-componentes; por ahora reusamos
// los existentes (Backtest.jsx, Optimizer.jsx, ResearchLog.jsx).

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { FlaskConical, Cpu, BookText } from "lucide-react";

import SectionHeader from "@/components/atoms/SectionHeader";
import { API_BASE } from "@/lib/api";

import Backtest from "@/sections/Backtest";
import Optimizer from "@/sections/Optimizer";
import ResearchLog from "@/sections/ResearchLog";

export default function Advanced() {
    return (
        <section className="px-6 lg:px-10 py-8" data-testid="page-advanced">
            <div className="max-w-[1400px] mx-auto">
                <SectionHeader
                    code="08 / AVANZADO"
                    title="Herramientas Avanzadas"
                    subtitle="Backtesting con datos sintéticos, optimizer de parámetros, y log de investigación."
                />

                <Tabs defaultValue="backtest" className="w-full">
                    <TabsList className="bg-[var(--surface)] border border-[var(--border)] flex flex-wrap h-auto p-0">
                        <TabsTrigger
                            value="backtest"
                            className="text-xs font-mono px-4 py-2 data-[state=active]:bg-[var(--surface-2)] data-[state=active]:text-[var(--green-bright)] flex items-center gap-2"
                        >
                            <FlaskConical size={12} />
                            Backtest
                        </TabsTrigger>
                        <TabsTrigger
                            value="optimizer"
                            className="text-xs font-mono px-4 py-2 data-[state=active]:bg-[var(--surface-2)] data-[state=active]:text-[var(--green-bright)] flex items-center gap-2"
                        >
                            <Cpu size={12} />
                            Optimizer
                        </TabsTrigger>
                        <TabsTrigger
                            value="research"
                            className="text-xs font-mono px-4 py-2 data-[state=active]:bg-[var(--surface-2)] data-[state=active]:text-[var(--green-bright)] flex items-center gap-2"
                        >
                            <BookText size={12} />
                            Research Log
                        </TabsTrigger>
                    </TabsList>

                    <TabsContent value="backtest" className="mt-4">
                        <Backtest api={API_BASE} />
                    </TabsContent>
                    <TabsContent value="optimizer" className="mt-4">
                        <Optimizer api={API_BASE} />
                    </TabsContent>
                    <TabsContent value="research" className="mt-4">
                        <ResearchLog api={API_BASE} />
                    </TabsContent>
                </Tabs>
            </div>
        </section>
    );
}
