import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";
import Overview from "./sections/Overview";
import MCPArchitecture from "./sections/MCPArchitecture";
import Strategies from "./sections/Strategies";
import Rules from "./sections/Rules";
import Checklist from "./sections/Checklist";
import RiskCalculator from "./sections/RiskCalculator";
import TradeJournal from "./sections/TradeJournal";
import SetupGuide from "./sections/SetupGuide";
import Mindset from "./sections/Mindset";
import ArchitectureDocs from "./sections/ArchitectureDocs";
import Footer from "./components/Footer";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function Dashboard() {
    const [planData, setPlanData] = useState(null);
    const [stats, setStats] = useState(null);
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

    useEffect(() => {
        fetchPlan();
        fetchStats();
    }, [fetchPlan, fetchStats]);

    // Section observer for sidebar active state
    useEffect(() => {
        const ids = [
            "overview",
            "mcps",
            "strategies",
            "rules",
            "checklist",
            "risk-calc",
            "journal",
            "setup",
            "mindset",
            "architecture-docs",
        ];
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
                <div className="kicker">// LOADING TRADING PLAN…</div>
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
                    <Overview config={planData.config} stats={stats} />
                    <MCPArchitecture mcps={planData.mcps} />
                    <Strategies strategies={planData.strategies} />
                    <Rules rules={planData.rules} />
                    <Checklist
                        checklist={planData.checklist}
                        api={API}
                    />
                    <RiskCalculator
                        api={API}
                        defaultBalance={planData.config.capital}
                    />
                    <TradeJournal
                        api={API}
                        strategies={planData.strategies}
                        stats={stats}
                        onMutated={fetchStats}
                    />
                    <SetupGuide steps={planData.setup_guide} />
                    <Mindset principles={planData.mindset} />
                    <ArchitectureDocs api={API} />
                    <Footer api={API} />
                </div>
            </main>
        </div>
    );
}
