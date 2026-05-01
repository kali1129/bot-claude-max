import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";

import ErrorBoundary from "@/components/ErrorBoundary";
import { SettingsProvider, useSettings } from "@/lib/userMode";
import { AuthProvider, RequireAdmin } from "@/lib/AuthProvider";
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
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import Admin from "@/pages/Admin";

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
                    {/* AuthProvider DENTRO del BrowserRouter — usa useNavigate */}
                    <AuthProvider>
                        <SettingsProvider>
                            <Routes>
                                {/* Auth — sin shell, sin onboarding gate */}
                                <Route path="/login" element={<Login />} />
                                <Route path="/register" element={<Register />} />

                                {/* Onboarding wizard — solo admin (Fase 1).
                                    En Fase 2 cada user tendrá su onboarding. */}
                                <Route
                                    path="/onboarding"
                                    element={
                                        <RequireAdmin>
                                            <RedirectIfOnboarded>
                                                <Onboarding />
                                            </RedirectIfOnboarded>
                                        </RequireAdmin>
                                    }
                                />

                                {/* Rutas read-only (cualquiera puede entrar) */}
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
                                    path="/ayuda"
                                    element={
                                        <ShellRoute>
                                            <Help />
                                        </ShellRoute>
                                    }
                                />

                                {/* Rutas admin-only (Fase 1) */}
                                <Route
                                    path="/configuracion"
                                    element={
                                        <ShellRoute>
                                            <RequireAdmin>
                                                <Settings />
                                            </RequireAdmin>
                                        </ShellRoute>
                                    }
                                />
                                <Route
                                    path="/avanzado"
                                    element={
                                        <ShellRoute>
                                            <RequireAdmin>
                                                <ExpertOnly>
                                                    <Advanced />
                                                </ExpertOnly>
                                            </RequireAdmin>
                                        </ShellRoute>
                                    }
                                />
                                <Route
                                    path="/admin"
                                    element={
                                        <ShellRoute>
                                            <RequireAdmin>
                                                <Admin />
                                            </RequireAdmin>
                                        </ShellRoute>
                                    }
                                />

                                {/* Catch-all → home */}
                                <Route path="*" element={<Navigate to="/" replace />} />
                            </Routes>
                        </SettingsProvider>
                    </AuthProvider>
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
