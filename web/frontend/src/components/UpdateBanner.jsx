import { useEffect, useState } from "react";
import { ArrowSquareOut, X } from "@phosphor-icons/react";
import { fetchVersionInfo } from "../api";

export default function UpdateBanner() {
  const [info, setInfo] = useState(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchVersionInfo()
      .then((data) => {
        if (!cancelled) setInfo(data);
      })
      .catch(() => {
        // No internet, GitHub unreachable, etc. — the app works fully
        // offline, so a failed update check is simply invisible, not an error.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!info?.update_available || dismissed) return null;

  return (
    <div className="update-banner">
      <span>
        A newer version (v{info.latest}) is available — you're on v{info.version}.
      </span>
      <a href={info.release_url} target="_blank" rel="noreferrer" className="update-banner__link">
        Download update
        <ArrowSquareOut size={14} weight="bold" />
      </a>
      <button className="update-banner__dismiss" onClick={() => setDismissed(true)} aria-label="Dismiss">
        <X size={16} weight="bold" />
      </button>
    </div>
  );
}
