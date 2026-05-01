// Admin — panel de administración (solo accesible con role=admin).
//
// Muestra:
//   - Stats agregadas (users totales, admins, regular, registrados 7d)
//   - Tabla de usuarios con: email, display_name, role, created_at,
//     status (Fase 2: cuenta MT5 conectada / bot activo)
//   - Acciones por user: ver detalle, promover a admin, demover, eliminar
//
// Solo accesible vía /admin (route protegida con RequireAdmin en App.js).

import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
    Users,
    Shield,
    UserPlus,
    UserMinus,
    Trash2,
    RefreshCcw,
    Cog,
    AlertTriangle,
    Mail,
    Calendar,
    Activity,
    Database,
} from "lucide-react";

import { apiGet, apiPatch, apiPost, apiDelete } from "@/lib/api";
import { useAuth } from "@/lib/AuthProvider";

import SectionHeader from "@/components/atoms/SectionHeader";
import KpiCard from "@/components/atoms/KpiCard";
import SkeletonPanel from "@/components/atoms/SkeletonPanel";
import EmptyState from "@/components/atoms/EmptyState";
import WarningModal from "@/components/atoms/WarningModal";

const formatDate = (iso) => {
    if (!iso) return "—";
    try {
        const d = new Date(iso);
        return d.toLocaleString("es-AR", {
            year: "numeric",
            month: "short",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        });
    } catch {
        return iso;
    }
};

export default function Admin() {
    const { user: currentUser } = useAuth();
    const [stats, setStats] = useState(null);
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [busyId, setBusyId] = useState(null);
    const [confirmDelete, setConfirmDelete] = useState(null);

    const navigate = useNavigate();

    const refresh = useCallback(async () => {
        try {
            const [s, u] = await Promise.allSettled([
                apiGet("/admin/stats"),
                apiGet("/admin/users"),
            ]);
            if (s.status === "fulfilled") setStats(s.value.data);
            if (u.status === "fulfilled") setUsers(u.value.data?.users || []);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        refresh();
        const id = setInterval(refresh, 15000);
        return () => clearInterval(id);
    }, [refresh]);

    const promote = async (userId, currentRole) => {
        const newRole = currentRole === "admin" ? "user" : "admin";
        setBusyId(userId);
        try {
            await apiPatch(`/admin/users/${userId}`, { role: newRole });
            toast.success(`Rol cambiado a ${newRole}`);
            refresh();
        } catch (e) {
            toast.error(e.response?.data?.detail || "No se pudo cambiar el rol");
        } finally {
            setBusyId(null);
        }
    };

    const remove = async () => {
        if (!confirmDelete) return;
        const userId = confirmDelete.id;
        setBusyId(userId);
        setConfirmDelete(null);
        try {
            await apiDelete(`/admin/users/${userId}`);
            toast.success("Usuario eliminado");
            refresh();
        } catch (e) {
            toast.error(e.response?.data?.detail || "No se pudo eliminar");
        } finally {
            setBusyId(null);
        }
    };

    const extendTrial = async (userId, days = 30) => {
        const input = window.prompt(`¿Cuántos días extender el trial?`, "30");
        if (!input) return;
        const d = parseInt(input, 10);
        if (!d || d <= 0 || d > 365) {
            toast.error("Días inválido (1-365)");
            return;
        }
        setBusyId(userId);
        try {
            const r = await apiPost(`/admin/users/${userId}/extend-trial`, { days: d });
            toast.success(`Trial extendido +${d} días — válido hasta ${new Date(r.data?.paid_until).toLocaleDateString()}`);
            refresh();
        } catch (e) {
            toast.error(e.response?.data?.detail || "Error extendiendo trial");
        } finally {
            setBusyId(null);
        }
    };

    const forceStop = async (userId) => {
        if (!window.confirm("¿Forzar el stop de su bot? El run se va a marcar como admin_force_stop.")) return;
        setBusyId(userId);
        try {
            await apiPost(`/admin/users/${userId}/force-stop-bot`, {});
            toast.success("Bot detenido por admin");
            refresh();
        } catch (e) {
            toast.error(e.response?.data?.detail || "Error force-stop");
        } finally {
            setBusyId(null);
        }
    };

    if (loading) {
        return (
            <section className="px-6 lg:px-10 py-8">
                <div className="max-w-[1400px] mx-auto">
                    <SectionHeader
                        code="ADMIN / PANEL"
                        title="Panel de administración"
                        subtitle="Cargando..."
                    />
                    <SkeletonPanel rows={6} />
                </div>
            </section>
        );
    }

    const userStats = stats?.users || {};

    return (
        <section className="px-6 lg:px-10 py-8" data-testid="page-admin">
            <div className="max-w-[1400px] mx-auto">
                <SectionHeader
                    code="ADMIN / PANEL"
                    title="Panel de administración"
                    subtitle="Gestión de usuarios y estadísticas globales del sistema."
                    action={
                        <button
                            type="button"
                            onClick={refresh}
                            className="btn-sharp flex items-center gap-2"
                            data-testid="admin-refresh"
                        >
                            <RefreshCcw size={12} />
                            Refrescar
                        </button>
                    }
                />

                {/* Stats cards */}
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
                    <KpiCard
                        label="Usuarios totales"
                        value={userStats.total ?? 0}
                        sublabel={`${userStats.registered_last_7d ?? 0} en últimos 7d`}
                        icon={Users}
                        color="white"
                        testId="admin-kpi-total"
                    />
                    <KpiCard
                        label="Admins"
                        value={userStats.admins ?? 0}
                        sublabel="control total"
                        icon={Shield}
                        color="green"
                        testId="admin-kpi-admins"
                    />
                    <KpiCard
                        label="Regulares"
                        value={userStats.regular ?? 0}
                        sublabel="role=user"
                        icon={UserPlus}
                        color="white"
                        testId="admin-kpi-regular"
                    />
                    <KpiCard
                        label="Bots activos / cupos"
                        value={`${stats?.slots?.active ?? 0}/${stats?.slots?.max_concurrent ?? "—"}`}
                        sublabel={`${stats?.slots?.available ?? 0} libre${(stats?.slots?.available ?? 0) !== 1 ? "s" : ""}`}
                        icon={Activity}
                        color={(stats?.slots?.available ?? 0) > 0 ? "green" : "red"}
                        testId="admin-kpi-slots"
                    />
                    <KpiCard
                        label="Trades en DB"
                        value={stats?.trades?.total ?? 0}
                        sublabel="journal global"
                        icon={Database}
                        color="white"
                        testId="admin-kpi-trades"
                    />
                </div>

                {/* Users table */}
                <div className="panel p-5" data-testid="admin-users-table">
                    <div className="flex items-center justify-between mb-3">
                        <div className="kicker">USUARIOS REGISTRADOS</div>
                        <span className="text-[10px] font-mono text-[var(--text-faint)]">
                            {users.length} usuario{users.length !== 1 ? "s" : ""}
                        </span>
                    </div>

                    {users.length === 0 ? (
                        <EmptyState
                            icon={<Users size={32} />}
                            title="No hay usuarios"
                            body="Cuando alguien se registre en /register, aparecerá acá."
                        />
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full font-mono text-xs">
                                <thead>
                                    <tr className="border-b border-[var(--border)] text-[var(--text-faint)]">
                                        <th className="text-left px-2 py-2 font-medium">Email</th>
                                        <th className="text-left px-2 py-2 font-medium">Nombre</th>
                                        <th className="text-left px-2 py-2 font-medium">Rol</th>
                                        <th className="text-left px-2 py-2 font-medium">
                                            Broker (Fase 2)
                                        </th>
                                        <th className="text-left px-2 py-2 font-medium">
                                            Bot (Fase 2)
                                        </th>
                                        <th className="text-left px-2 py-2 font-medium">
                                            Registrado
                                        </th>
                                        <th className="text-right px-2 py-2 font-medium">
                                            Acciones
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {users.map((u) => {
                                        const isMe = u.id === currentUser?.id;
                                        const isAdminRole = u.role === "admin";
                                        const isBusy = busyId === u.id;
                                        return (
                                            <tr
                                                key={u.id}
                                                className="border-b border-[var(--border)] hover:bg-[var(--surface)]"
                                                data-testid={`admin-user-row-${u.id}`}
                                            >
                                                <td className="px-2 py-2.5">
                                                    <div className="flex items-center gap-1.5">
                                                        <Mail
                                                            size={10}
                                                            className="text-[var(--text-faint)]"
                                                        />
                                                        <span className="truncate max-w-[200px]">
                                                            {u.email}
                                                        </span>
                                                        {isMe ? (
                                                            <span className="kicker text-[8px] text-[var(--green-bright)]">
                                                                YOU
                                                            </span>
                                                        ) : null}
                                                    </div>
                                                </td>
                                                <td className="px-2 py-2.5 text-[var(--text-dim)]">
                                                    {u.display_name || "—"}
                                                </td>
                                                <td className="px-2 py-2.5">
                                                    <span
                                                        className={`px-2 py-0.5 text-[10px] border ${
                                                            isAdminRole
                                                                ? "border-[var(--green)] text-[var(--green-bright)]"
                                                                : "border-[var(--border)] text-[var(--text-dim)]"
                                                        }`}
                                                    >
                                                        {isAdminRole ? "ADMIN" : "USER"}
                                                    </span>
                                                </td>
                                                                <td className="px-2 py-2.5">
                                                    {(u.broker_accounts && u.broker_accounts.length > 0) ? (
                                                        <div className="flex flex-col gap-0.5">
                                                            {u.broker_accounts.map((a) => (
                                                                <div
                                                                    key={a.id || `${a.is_demo}_${a.mt5_login}`}
                                                                    className="flex items-center gap-1 text-[10px]"
                                                                    title={`${a.is_demo ? "DEMO" : "REAL"} · ${a.mt5_server}`}
                                                                >
                                                                    <span
                                                                        className="kicker"
                                                                        style={{
                                                                            color: a.is_active
                                                                                ? "var(--green-bright)"
                                                                                : "var(--text-faint)",
                                                                        }}
                                                                    >
                                                                        {a.is_active ? "★" : "○"}
                                                                    </span>
                                                                    <span
                                                                        style={{
                                                                            color: a.is_demo
                                                                                ? "var(--blue)"
                                                                                : "var(--amber)",
                                                                        }}
                                                                    >
                                                                        {a.is_demo ? "DEMO" : "REAL"}
                                                                    </span>
                                                                    <span className="text-[9px] text-[var(--text-faint)]">
                                                                        {a.mt5_login}
                                                                    </span>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    ) : u.broker_connected ? (
                                                        // Fallback compat (server viejo sin broker_accounts)
                                                        <div className="flex items-center gap-1">
                                                            <span className="kicker text-[var(--green-bright)]">●</span>
                                                            <span className="text-[10px]">
                                                                {u.broker_login} · {u.broker_demo ? "DEMO" : "REAL"}
                                                            </span>
                                                        </div>
                                                    ) : (
                                                        <span className="text-[var(--text-faint)] italic text-[10px]">
                                                            no conectado
                                                        </span>
                                                    )}
                                                </td>
                                                <td className="px-2 py-2.5">
                                                    {u.bot_running ? (
                                                        <div className="flex flex-col">
                                                            <span className="kicker text-[var(--green-bright)]">
                                                                ● ACTIVO
                                                            </span>
                                                            {u.bot_systemd ? (
                                                                <span className="text-[9px] text-[var(--green-bright)]">
                                                                    bot global (systemd)
                                                                </span>
                                                            ) : u.trial_seconds_remaining != null ? (
                                                                <span className="text-[9px] text-[var(--text-faint)]">
                                                                    {u.trial_expired ? (
                                                                        <span className="text-[var(--red)]">trial vencido</span>
                                                                    ) : (
                                                                        <>
                                                                            {Math.floor(u.trial_seconds_remaining / 3600)}h {Math.floor((u.trial_seconds_remaining % 3600) / 60)}m
                                                                        </>
                                                                    )}
                                                                </span>
                                                            ) : (
                                                                <span className="text-[9px] text-[var(--green-bright)]">sin límite</span>
                                                            )}
                                                        </div>
                                                    ) : (
                                                        <span className="text-[var(--text-faint)] italic text-[10px]">
                                                            {isAdminRole ? "systemd inactivo" : "inactivo"}
                                                        </span>
                                                    )}
                                                </td>
                                                <td className="px-2 py-2.5 text-[var(--text-dim)]">
                                                    <span className="flex items-center gap-1">
                                                        <Calendar
                                                            size={10}
                                                            className="text-[var(--text-faint)]"
                                                        />
                                                        {formatDate(u.created_at)}
                                                    </span>
                                                </td>
                                                <td className="px-2 py-2.5 text-right">
                                                    <div className="flex items-center justify-end gap-1 flex-wrap">
                                                        {!isMe ? (
                                                            <>
                                                                {u.bot_running && !isAdminRole ? (
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => extendTrial(u.id)}
                                                                        disabled={isBusy}
                                                                        className="btn-sharp success text-[10px] px-2 py-1"
                                                                        title="Extender trial (días)"
                                                                        data-testid={`admin-extend-${u.id}`}
                                                                    >
                                                                        +Trial
                                                                    </button>
                                                                ) : null}
                                                                {u.bot_running ? (
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => forceStop(u.id)}
                                                                        disabled={isBusy}
                                                                        className="btn-sharp text-[10px] px-2 py-1"
                                                                        title="Forzar stop del bot"
                                                                        data-testid={`admin-stop-${u.id}`}
                                                                    >
                                                                        Stop
                                                                    </button>
                                                                ) : null}
                                                                <button
                                                                    type="button"
                                                                    onClick={() =>
                                                                        promote(u.id, u.role)
                                                                    }
                                                                    disabled={isBusy}
                                                                    className="btn-sharp text-[10px] px-2 py-1 flex items-center gap-1"
                                                                    title={
                                                                        isAdminRole
                                                                            ? "Quitar rol admin"
                                                                            : "Promover a admin"
                                                                    }
                                                                    data-testid={`admin-promote-${u.id}`}
                                                                >
                                                                    {isAdminRole ? (
                                                                        <UserMinus size={10} />
                                                                    ) : (
                                                                        <Shield size={10} />
                                                                    )}
                                                                </button>
                                                                <button
                                                                    type="button"
                                                                    onClick={() =>
                                                                        setConfirmDelete(u)
                                                                    }
                                                                    disabled={isBusy}
                                                                    className="btn-sharp danger text-[10px] px-2 py-1"
                                                                    title="Eliminar usuario"
                                                                    data-testid={`admin-delete-${u.id}`}
                                                                >
                                                                    <Trash2 size={10} />
                                                                </button>
                                                            </>
                                                        ) : (
                                                            <span className="text-[10px] text-[var(--text-faint)] italic">
                                                                tu cuenta
                                                            </span>
                                                        )}
                                                    </div>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>

                {/* Roadmap Fase 2 — info para admin */}
                <div
                    className="panel mt-5 p-5 border-l-2"
                    style={{
                        borderLeftColor: "var(--blue)",
                        background: "rgba(59,130,246,0.04)",
                    }}
                >
                    <div className="flex items-start gap-2">
                        <Activity
                            size={14}
                            className="text-[var(--blue)] mt-0.5"
                        />
                        <div className="flex-1">
                            <div className="kicker text-[var(--blue)] mb-1">
                                ROADMAP — FASE 2 (próxima sesión)
                            </div>
                            <p className="text-[11px] text-[var(--text-dim)] leading-relaxed">
                                Acá vas a poder ver, por usuario:
                            </p>
                            <ul className="text-[11px] text-[var(--text-dim)] list-disc list-inside mt-1 leading-relaxed">
                                <li>Cuenta MT5 conectada (broker, login, demo/real)</li>
                                <li>Bot activo o pausado, P&L de su cuenta, trades hoy</li>
                                <li>Estilo (conservativo/balanceado/agresivo) y sesiones</li>
                                <li>Telegram chats configurados</li>
                                <li>Acciones admin: forzar pausa de su bot, ver logs, etc.</li>
                            </ul>
                            <p className="text-[10px] text-[var(--text-faint)] mt-2 italic">
                                Por ahora (FASE 1), todos los usuarios ven la cuenta del admin
                                en read-only. La FASE 2 va a aislar cada usuario a su propia
                                cuenta MT5.
                            </p>
                        </div>
                    </div>
                </div>
            </div>

            {/* Modal de confirmación delete */}
            <WarningModal
                open={!!confirmDelete}
                onOpenChange={(o) => {
                    if (!o) setConfirmDelete(null);
                }}
                title={`¿Eliminar ${confirmDelete?.email}?`}
                body={
                    <div className="space-y-2 text-sm">
                        <p>
                            Vas a eliminar la cuenta de{" "}
                            <strong>{confirmDelete?.email}</strong> permanentemente.
                        </p>
                        <p className="text-[var(--text-faint)]">
                            En FASE 2 esto también va a desconectar su MT5 y detener
                            su bot. Por ahora solo borra la cuenta del sistema.
                        </p>
                    </div>
                }
                checkboxText="Entiendo. Esta acción es permanente."
                confirmLabel="Sí, eliminar"
                cancelLabel="Cancelar"
                danger
                onConfirm={remove}
            />
        </section>
    );
}
