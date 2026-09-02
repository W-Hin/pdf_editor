import { Routes, Route, Link } from "react-router-dom";
import { FilePdf, ClockCounterClockwise } from "@phosphor-icons/react";
import ToolGrid from "./components/ToolGrid.jsx";
import ToolView from "./components/ToolView.jsx";
import UpdateBanner from "./components/UpdateBanner.jsx";

export default function App() {
  return (
    <div className="app">
      <header className="app__header">
        <Link to="/" className="app__brand">
          <FilePdf size={22} weight="fill" />
          PDF Editor
        </Link>
        <nav className="app__nav">
          <Link to="/#recent-files">
            <ClockCounterClockwise size={18} weight="regular" />
            Recent Files
          </Link>
        </nav>
      </header>
      <UpdateBanner />
      <main className="app__main">
        <Routes>
          <Route path="/" element={<ToolGrid />} />
          <Route path="/tool/:toolId" element={<ToolView />} />
        </Routes>
      </main>
    </div>
  );
}
