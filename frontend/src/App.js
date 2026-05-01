import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";

import ErrorBoundary from "@/components/ErrorBoundary";
import { SettingsProvider, useSettings } from "@/lib/userMode";
import { OnboardingGate, RedirectIfOnboarded } from "@/lib/onboardingGate";

import AppShell from "@/components/AppShell";

import Onboarding from "@/pages/Onboarding";
import Home from "@/pages/Home";
import Settings from "@/pages/Settings";
import Trades from "@/pages/Trades";
import StrategiesPage from "@/pages/Strategies";
import Stats from "@/pages/Stats";
import Help from "@/pages/Help";
import Advanced from "@/pages/Advanced";
import Live from "@/pages/Live";

// Wrapper que combina OnboardingGate + AppShell (sidebar + topbar) para
// las rutas "normales" del dashboard.
function ShellRoute({ children }) {
    return (
        <OnboardingGate>
            <AppShell>{children}</AppShell>
        </OnboardingGate>
    );
}

// Ruta solo accesible en modo experto. Si novato → 403 friendly.
function ExpertOnly({ children }) {
    const { isExperto } = useSettings();
    if (!isExperto) {
        return (
            <div
                className="min-h-[60vh] flex items-center justify-center px-6"
                data-testid="expert-only-block"
            >
                <div className="panel p-8 max-w-md text-center">
                    <div className="kicker mb-3">// SECCIÓN BLOQUEADA</div>
                    <h2 className="font-display text-2xl font-black mb-3">
                        Esta sección requiere modo Experto
                    </h2>
                    <p className="text-sm text-[var(--text-dim)] mb-5">
                        Acá viven herramientas avanzadas (Backtesting, Optimizer,
                        Monte Carlo, Research Log). Si querés activarlas, andá a
                        Configuración y cambiá el modo a Experto.
                    </p>
                    <a href="/configuracion" className="btn-sharp primary">
                        Ir a Configuración
                    </a>
                </div>
            </div>
        );
    }
    return children;
}

function App() {
    return (
        <div className="App">
            <ErrorBoundary>
                <BrowserRouter>
                    <SettingsProvider>
                        <Routes>
                            {/* Onboarding wizard — sin sidebar/topbar */}
                            <Route
                                path="/onboarding"
                                element={
                                    <RedirectIfOnboarded>
                                        <Onboarding />
                                    </RedirectIfOnboarded>
                                }
                            />

                            {/* Rutas principales con shell */}
                            <Route
                                path="/"
                                element={
                                    <ShellRoute>
                                        <Home />
                                    </ShellRoute>
                                }
                            />
                            <Route
                                path="/vivo"
                                element={
                                    <ShellRoute>
                                        <Live />
                                    </ShellRoute>
                                }
                            />
                            <Route
                                path="/operaciones"
                                element={
                                    <ShellRoute>
                                        <Trades />
                                    </ShellRoute>
                                }
                            />
                            <Route
                                path="/estrategias"
                                element={
                                    <ShellRoute>
                                        <StrategiesPage />
                                    </ShellRoute>
                                }
                            />
                            <Route
                                path="/estadisticas"
                                element={
                                    <ShellRoute>
                                        <Stats />
                                    </ShellRoute>
                                }
                            />
                            <Route
                                path="/configuracion"
                                element={
                                    <ShellRoute>
                                        <Settings />
                                    </ShellRoute>
                                }
                            />
                            <Route
                                path="/ayuda"
                                element={
                                    <ShellRoute>
                                        <Help />
                                    </ShellRoute>
                                }
                            />
                            <Route
                                path="/avanzado"
                                element={
                                    <ShellRoute>
                                        <ExpertOnly>
                                            <Advanced />
                                        </ExpertOnly>
                                    </ShellRoute>
                                }
                            />

                            {/* Catch-all → home */}
                            <Route path="*" element={<Navigate to="/" replace />} />
                        </Routes>
                    </SettingsProvider>
                </BrowserRouter>
            </ErrorBoundary>
            <Toaster
                theme="dark"
                position="bottom-right"
                toastOptions={{
                    style: {
                        background: "#121214",
                        border: "1px solid #27272a",
                        color: "#f4f4f5",
                        fontFamily: "JetBrains Mono, monospace",
                        fontSize: "12px",
                        borderRadius: 0,
                    },
                }}
            />
        </div>
    );
}

export default App;
