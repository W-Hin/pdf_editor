const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      // response wasn't JSON; keep statusText
    }
    throw new Error(detail);
  }
  return res;
}

export async function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await request("/files", { method: "POST", body: formData });
  return res.json();
}

export function thumbnailUrl(fileId, pageNumber, maxSize) {
  const query = maxSize ? `?max_size=${maxSize}` : "";
  return `${BASE}/files/${fileId}/pages/${pageNumber}/thumbnail${query}`;
}

export function downloadUrl(fileId) {
  return `${BASE}/files/${fileId}/download`;
}

export async function runTool(toolPath, body) {
  const res = await request(`/tools/${toolPath}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

export async function fetchHistory() {
  const res = await request("/history");
  return res.json();
}

export async function deleteHistoryEntry(fileId) {
  await request(`/history/${fileId}`, { method: "DELETE" });
}

export async function fetchVersionInfo() {
  // Best-effort: /api/version never errors (it swallows its own network
  // failures server-side), so a plain fetch is enough — no error banner
  // to show if this fails, the update check just silently does nothing.
  const res = await fetch(`${BASE}/version`);
  return res.json();
}
