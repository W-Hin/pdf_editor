import { Routes, Route, Link } from "react-router-dom";
import ToolGrid from "./components/ToolGrid.jsx";

export default function App() {
  return (
    <div className="app">
      <header className="app__header">
        <Link to="/" className="app__brand">
          PDF Editor
        </Link>
      </header>
      <main className="app__main">
        <Routes>
          <Route path="/" element={<ToolGrid />} />
        </Routes>
      </main>
    </div>
  );
}
