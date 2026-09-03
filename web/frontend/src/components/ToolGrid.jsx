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
  FileImage,
  FileDoc,
  Crop,
  ListNumbers,
  Eraser,
  NotePencil,
  Signature,
  File,
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
  crop: Crop,
  "add-page-numbers": ListNumbers,
  "to-images": Image,
  "to-word": FileDoc,
  "images-to-pdf": FileImage,
  redact: Eraser,
  "edit-pdf": NotePencil,
  sign: Signature,
};

// Development-time early warning: a tool added to TOOL_CONFIGS without a
// matching TOOL_ICONS entry silently ships with the generic `?? File` fallback
// icon, which has slipped through review three times. console.error (not throw)
// keeps the fallback as the runtime safety net while making the gap loud in dev.
if (import.meta.env.DEV) {
  const missing = Object.keys(TOOL_CONFIGS).filter((id) => !(id in TOOL_ICONS));
  if (missing.length > 0) {
    console.error(`TOOL_ICONS is missing entries for: ${missing.join(", ")}`);
  }
}

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
                  // Fall back to a generic icon so a tool added to TOOL_CONFIGS
                  // without a matching TOOL_ICONS entry degrades gracefully
                  // instead of crashing the whole grid.
                  const Icon = TOOL_ICONS[toolId] ?? File;
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
