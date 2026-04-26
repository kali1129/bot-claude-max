import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Dashboard from "./Dashboard";
import { Toaster } from "sonner";

function App() {
    return (
        <div className="App">
            <BrowserRouter>
                <Routes>
                    <Route path="/" element={<Dashboard />} />
                </Routes>
            </BrowserRouter>
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
