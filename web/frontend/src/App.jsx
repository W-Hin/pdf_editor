import { Routes, Route, Link } from "react-router-dom";

function Home() {
  return <h1>PDF Editor</h1>;
}

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
          <Route path="/" element={<Home />} />
        </Routes>
      </main>
    </div>
  );
}
