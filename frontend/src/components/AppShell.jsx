// AppShell
// Layout compartido por todas las rutas del dashboard:
//   - Sidebar fijo a la izquierda en desktop (drawer en mobile)
//   - TopBar sticky arriba
//   - Banner persistente si style=agresivo
//   - Slot {children} = la página
//
// Reemplaza Dashboard.jsx, que usaba scroll-spy y todas las secciones
// renderizadas a la vez. Ahora cada ruta es independiente.

import { useState } from "react";
import { Menu } from "lucide-react";
import { Sheet, SheetContent } from "@/components/ui/sheet";

import Sidebar from "@/components/Sidebar";
import TopBar from "@/components/TopBar";
import AggressiveBanner from "@/components/atoms/AggressiveBanner";

export default function AppShell({ children }) {
    const [mobileOpen, setMobileOpen] = useState(false);

    return (
        <div className="min-h-screen flex bg-[var(--bg)]" data-testid="app-shell">
            {/* Desktop sidebar */}
            <div className="hidden lg:block">
                <Sidebar />
            </div>

            {/* Mobile drawer sidebar */}
            <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
                <SheetContent
                    side="left"
                    className="p-0 w-[260px] bg-[var(--surface)] border-[var(--border)]"
                >
                    <Sidebar
                        mobile
                        onNavigate={() => setMobileOpen(false)}
                    />
                </SheetContent>
            </Sheet>

            <main
                className="flex-1 lg:ml-[var(--sidebar-w,240px)] min-w-0"
                data-testid="main-content"
            >
                {/* Hamburger trigger only on mobile */}
                <button
                    type="button"
                    onClick={() => setMobileOpen(true)}
                    className="lg:hidden fixed top-3 left-3 z-40 btn-sharp"
                    aria-label="Abrir menú"
                    data-testid="mobile-menu-toggle"
                >
                    <Menu size={14} />
                </button>

                <AggressiveBanner />

                <TopBar />

                <div className="grid-bg min-h-[calc(100vh-120px)]">{children}</div>
            </main>
        </div>
    );
}
