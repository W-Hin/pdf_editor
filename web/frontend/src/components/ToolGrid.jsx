import { useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  Stack,
  Scissors,
  FileX,
  FileArrowDown,
  ArrowsDownUp,
  ArrowClockwise,
  Drop,
  ArrowsInSimple,
  Image,
  FileDoc,
} from "@phosphor-icons/react";
import { TOOL_CONFIGS } from "../toolConfigs";
import RecentFiles from "./RecentFiles.jsx";

const CATEGORIES = ["Organize", "Edit", "Optimize", "Convert"];

const TOOL_ICONS = {
  merge: Stack,
  split: Scissors,
  "remove-pages": FileX,
  "extract-pages": FileArrowDown,
  "reorder-pages": ArrowsDownUp,
  rotate: ArrowClockwise,
  watermark: Drop,
  compress: ArrowsInSimple,
  "to-images": Image,
  "to-word": FileDoc,
};

export default function ToolGrid() {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (location.hash === "#recent-files") {
      document.getElementById("recent-files")?.scrollIntoView({ behavior: "smooth" });
    }
  }, [location]);

  return (
    <div className="tool-grid-page">
      <div className="tool-grid">
        {CATEGORIES.map((category) => {
          const tools = Object.entries(TOOL_CONFIGS).filter(([, cfg]) => cfg.category === category);
          return (
            <div key={category} className="tool-grid__category">
              <h2>{category}</h2>
              <div className="tool-grid__buttons">
                {tools.map(([toolId, cfg]) => {
                  const Icon = TOOL_ICONS[toolId];
                  return (
                    <button key={toolId} onClick={() => navigate(`/tool/${toolId}`)}>
                      <span className="tool-grid__icon">
                        <Icon size={20} weight="regular" />
                      </span>
                      {cfg.title}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      <RecentFiles />
    </div>
  );
}
