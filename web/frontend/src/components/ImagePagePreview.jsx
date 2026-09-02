import { useState } from "react";
import { thumbnailUrl } from "../api";

export default function ImagePagePreview({ fileId, fitMode }) {
  const [orientation, setOrientation] = useState("portrait");

  function handleLoad(e) {
    const { naturalWidth: w, naturalHeight: h } = e.target;
    if (!w || !h) return;
    setOrientation(w > h ? "landscape" : "portrait");
  }

  return (
    <div className={`image-page-preview image-page-preview--${orientation}`}>
      <img
        src={thumbnailUrl(fileId, 1)}
        alt=""
        onLoad={handleLoad}
        style={{ objectFit: fitMode === "fill" ? "cover" : "contain" }}
      />
    </div>
  );
}
