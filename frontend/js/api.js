/* Thin fetch wrapper for the backend API. Throws an Error with `.status` and `.detail`
 * so callers can show the server's message. */
window.API = (() => {
  async function request(method, path, body) {
    const init = { method, headers: {} };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const res = await fetch(path, init);
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (_) { data = text; }
    if (!res.ok) {
      const err = new Error((data && data.detail) || res.statusText || "request failed");
      err.status = res.status;
      err.detail = data && data.detail;
      throw err;
    }
    return data;
  }
  return {
    get: (p) => request("GET", p),
    post: (p, b) => request("POST", p, b),
    put: (p, b) => request("PUT", p, b),
    patch: (p, b) => request("PATCH", p, b),
    del: (p) => request("DELETE", p),
    health: () => request("GET", "/health"),
  };
})();
