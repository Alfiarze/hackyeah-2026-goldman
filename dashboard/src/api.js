const KEY = "mandate.adminKey";

export function getKey() {
  try { return localStorage.getItem(KEY) || "dev-admin-key"; } catch { return "dev-admin-key"; }
}
export function setKey(k) {
  try { localStorage.setItem(KEY, k); } catch { /* private mode */ }
}

export async function api(path, { method = "GET", body, text } = {}) {
  const headers = { "X-Admin-Key": getKey() };
  let payload;
  if (text !== undefined) { headers["Content-Type"] = "text/plain"; payload = text; }
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const res = await fetch(path, { method, headers, body: payload });
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    const msg = data?.error?.message || data?.error?.reason_code || data?.detail || res.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

export function download(path, filename) {
  fetch(path, { headers: { "X-Admin-Key": getKey() } })
    .then((r) => r.blob())
    .then((b) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(b);
      a.download = filename;
      a.click();
      URL.revokeObjectURL(a.href);
    });
}
