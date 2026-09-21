/* Thin fetch wrapper for the backend API. Throws an Error with `.status` and `.detail`
 * so callers can show the server's message. */
window.API = (() => {
  /* Server `detail` is normally a string; FastAPI's default validation payload is a list
   * of {loc, msg} and a bare 500 is plain text. Never let "[object Object]" reach a toast. */
  function describe(detail) {
    if (detail == null) return "";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((e) => {
        if (typeof e === "string") return e;
        const loc = (e.loc || []).filter((x) => x !== "body" && x !== "attrs").join(".");
        return loc ? `${loc}: ${e.msg}` : e.msg || JSON.stringify(e);
      }).join("; ");
    }
    return detail.msg || detail.message || JSON.stringify(detail);
  }
  async function request(method, path, body) {
    // X-Locale lets the backend translate domain error messages (see app.main).
    const init = { method, headers: { "X-Locale": (window.I18N && window.I18N.locale) || "en" } };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const res = await fetch(path, init);
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (_) { data = text; }
    if (!res.ok) {
      const detail = describe(data && data.detail);
      const err = new Error(detail || res.statusText || "request failed");
      err.status = res.status;
      err.detail = detail;
      err.code = data && data.code;
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
