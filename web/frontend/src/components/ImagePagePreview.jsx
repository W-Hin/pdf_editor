import { useState } from "react";
import { FileImage } from "@phosphor-icons/react";
import { thumbnailUrl } from "../api";

export default function ImagePagePreview({ fileId, fitMode }) {
  const [orientation, setOrientation] = useState("portrait");
  const [failed, setFailed] = useState(false);

  function handleLoad(e) {
    const { naturalWidth: w, naturalHeight: h } = e.target;
    if (!w || !h) return;
    setOrientation(w > h ? "landscape" : "portrait");
  }

  return (
    <div className={`image-page-preview image-page-preview--${orientation}`}>
      {failed ? (
        // The thumbnail request can legitimately fail (e.g. a corrupt image the
        // backend refuses to render) — show a placeholder rather than a broken
        // image box.
        <div className="image-page-preview__error">
          <FileImage size={32} weight="thin" />
        </div>
      ) : (
        <img
          src={thumbnailUrl(fileId, 1)}
          alt=""
          onLoad={handleLoad}
          onError={() => setFailed(true)}
          style={{ objectFit: fitMode === "fill" ? "cover" : "contain" }}
        />
      )}
    </div>
  );
}
