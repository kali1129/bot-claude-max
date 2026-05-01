// AuthCorner — pill superior-derecha que muestra el estado de auth.
//
// 3 modos:
//   - Anónimo: botón "Iniciar sesión" + link "Crear cuenta".
//   - Logged user (no admin): pill con email + botón Salir.
//   - Logged admin: pill con email + badge ADMIN + botón Salir.
//
// Usa Radix DropdownMenu (Portal + z-index correcto) para evitar que el
// dropdown quede oculto por overflow:hidden de algún parent. La versión
// anterior usaba absolute positioning y a veces no se veía / no permitía
// hacer click en "Cerrar sesión".

import { Link } from "react-router-dom";
import { LogIn, LogOut, User, Shield, ChevronDown } from "lucide-react";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/lib/AuthProvider";

export default function AuthCorner() {
    const { user, isAdmin, isAuthenticated, logout } = useAuth();

    if (!isAuthenticated) {
        return (
            <Link
                to="/login"
                className="btn-sharp flex items-center gap-2"
                data-testid="auth-login-link"
                title="Iniciar sesión"
            >
                <LogIn size={12} />
                <span className="hidden sm:inline">Entrar</span>
            </Link>
        );
    }

    const label = user?.display_name || user?.email || "Usuario";

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <button
                    type="button"
                    className={`btn-sharp flex items-center gap-2 ${isAdmin ? "primary" : ""}`}
                    data-testid="auth-user-pill"
                    title={user?.email}
                >
                    {isAdmin ? <Shield size={12} /> : <User size={12} />}
                    <span className="hidden sm:inline truncate max-w-[120px]">
                        {label}
                    </span>
                    <ChevronDown size={11} />
                </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
                align="end"
                className="w-56 bg-[var(--surface-2)] border-[var(--border)] z-[100]"
                sideOffset={4}
            >
                <DropdownMenuLabel className="font-mono">
                    <div className="kicker mb-0.5">
                        {isAdmin ? "ADMIN" : "USUARIO"}
                    </div>
                    <div className="text-xs truncate font-normal text-[var(--text)]">
                        {user?.email}
                    </div>
                </DropdownMenuLabel>
                {!isAdmin ? (
                    <>
                        <DropdownMenuSeparator className="bg-[var(--border)]" />
                        <div className="px-2 py-1.5 text-[10px] text-[var(--text-faint)]">
                            Modo demo. Pronto vas a poder conectar tu propia cuenta.
                        </div>
                    </>
                ) : null}
                <DropdownMenuSeparator className="bg-[var(--border)]" />
                <DropdownMenuItem
                    onSelect={(e) => {
                        // Radix se cierra automáticamente; logout navega
                        e.preventDefault();
                        logout();
                    }}
                    className="text-[var(--red)] focus:text-[var(--red)] focus:bg-[var(--surface)] cursor-pointer flex items-center gap-2 text-xs font-mono"
                    data-testid="auth-logout-btn"
                >
                    <LogOut size={11} />
                    Cerrar sesión
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
