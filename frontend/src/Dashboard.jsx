import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";
import LiveDashboard from "./sections/LiveDashboard";
import Overview from "./sections/Overview";
import ControlPanel from "./sections/ControlPanel";
import ConfigPanel from "./sections/ConfigPanel";
import TradeJournal from "./sections/TradeJournal";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function Dashboard() {
    const [planData, setPlanData] = useState(null);
    const [stats, setStats] = useState(null);
    const [botConfig, setBotConfig] = useState(null);
    const [activeSection, setActiveSection] = useState("overview");

    const fetchPlan = useCallback(async () => {
        try {
            const res = await axios.get(`${API}/plan/data`);
            setPlanData(res.data);
        } catch (e) {
            console.error("plan/data error", e);
        }
    }, []);

    const fetchStats = useCallback(async () => {
        try {
            const res = await axios.get(`${API}/journal/stats`);
            setStats(res.data);
        } catch (e) {
            console.error("journal/stats error", e);
        }
    }, []);

    const fetchBotConfig = useCallback(async () => {
        try {
            const res = await axios.get(`${API}/bot/config`);
            setBotConfig(res.data);
        } catch (e) {
            console.error("bot/config error", e);
        }
    }, []);

    useEffect(() => {
        fetchPlan();
        fetchStats();
        fetchBotConfig();
        const id = setInterval(fetchStats, 8000);
        return () => clearInterval(id);
    }, [fetchPlan, fetchStats, fetchBotConfig]);

    useEffect(() => {
        const ids = ["live", "overview", "control", "config", "journal"];
        const observer = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        setActiveSection(entry.target.id);
                    }
                });
            },
            { rootMargin: "-30% 0px -60% 0px", threshold: 0 }
        );
        ids.forEach((id) => {
            const el = document.getElementById(id);
            if (el) observer.observe(el);
        });
        return () => observer.disconnect();
    }, [planData]);

    if (!planData) {
        return (
            <div
                className="min-h-screen flex items-center justify-center"
                data-testid="loading-screen"
            >
                <div className="kicker">// CARGANDO…</div>
            </div>
        );
    }

    return (
        <div className="min-h-screen flex" data-testid="dashboard-root">
            <Sidebar activeSection={activeSection} />

            <main className="flex-1 lg:ml-[240px] min-w-0">
                <TopBar
                    config={planData.config}
                    stats={stats}
                    onRefreshStats={fetchStats}
                />

                <div className="grid-bg">
                    <LiveDashboard api={API} />
                    <Overview config={planData.config} stats={stats} />
                    <ControlPanel api={API} onMutated={fetchStats} />
                    <ConfigPanel
                        api={API}
                        config={botConfig}
                        onMutated={() => {
                            fetchStats();
                            fetchBotConfig();
                        }}
                    />
                    <TradeJournal
                        api={API}
                        strategies={planData.strategies}
                        stats={stats}
                        onMutated={fetchStats}
                    />
                </div>
            </main>
        </div>
    );
}
