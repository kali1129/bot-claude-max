import { Component } from "react";

export default class ErrorBoundary extends Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null, info: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, info) {
        this.setState({ info });
        console.error("[ErrorBoundary]", error, info);
    }

    render() {
        if (this.state.hasError) {
            return (
                <div style={{
                    padding: "40px",
                    background: "#0a0a0a",
                    color: "#f87171",
                    fontFamily: "JetBrains Mono, monospace",
                    fontSize: "13px",
                    minHeight: "100vh",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                }}>
                    <h2 style={{ color: "#ef4444", marginBottom: "16px" }}>
                        ⚠ Dashboard Error
                    </h2>
                    <p style={{ color: "#fbbf24", marginBottom: "8px" }}>
                        {this.state.error?.toString()}
                    </p>
                    <details open>
                        <summary style={{ cursor: "pointer", color: "#71717a" }}>Stack trace</summary>
                        <pre style={{ color: "#a1a1aa", marginTop: "8px", fontSize: "11px" }}>
                            {this.state.info?.componentStack}
                        </pre>
                    </details>
                    <button
                        onClick={() => window.location.reload()}
                        style={{
                            marginTop: "24px",
                            padding: "8px 20px",
                            background: "#27272a",
                            color: "#e4e4e7",
                            border: "1px solid #3f3f46",
                            cursor: "pointer",
                            fontFamily: "inherit",
                        }}
                    >
                        Recargar
                    </button>
                </div>
            );
        }
        return this.props.children;
    }
}
