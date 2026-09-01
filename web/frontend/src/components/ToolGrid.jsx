import { useNavigate } from "react-router-dom";
import { TOOL_CONFIGS } from "../toolConfigs";

const CATEGORIES = ["Organize", "Edit", "Optimize", "Convert"];

export default function ToolGrid() {
  const navigate = useNavigate();

  return (
    <div className="tool-grid">
      {CATEGORIES.map((category) => {
        const tools = Object.entries(TOOL_CONFIGS).filter(([, cfg]) => cfg.category === category);
        return (
          <div key={category} className="tool-grid__category">
            <h2>{category}</h2>
            <div className="tool-grid__buttons">
              {tools.map(([toolId, cfg]) => (
                <button key={toolId} onClick={() => navigate(`/tool/${toolId}`)}>
                  {cfg.title}
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
