import { Routes, Route, Link } from "react-router-dom";
import ToolGrid from "./components/ToolGrid.jsx";
import ToolView from "./components/ToolView.jsx";
import RecentFiles from "./components/RecentFiles.jsx";

export default function App() {
  return (
    <div className="app">
      <header className="app__header">
        <Link to="/" className="app__brand">
          PDF Editor
        </Link>
        <nav className="app__nav">
          <Link to="/recent">Recent Files</Link>
        </nav>
      </header>
      <main className="app__main">
        <Routes>
          <Route path="/" element={<ToolGrid />} />
          <Route path="/tool/:toolId" element={<ToolView />} />
          <Route path="/recent" element={<RecentFiles />} />
        </Routes>
      </main>
    </div>
  );
}
