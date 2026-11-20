import { API } from "./config.js";

/**
 * Every call to the backend goes through api().
 *  - credentials: "same-origin" makes the browser attach the httpOnly session cookie.
 *    (JavaScript never sees the cookie, so a script injected into the page cannot steal it.)
 *  - X-Requested-With is the "CSRF header" the backend requires on POST/PATCH: other websites
 *    cannot add custom headers to cross-site requests, so this proves the call came from our app.
 *  - Errors from the backend look like {error:{code,message,fields}}; we turn them into ApiError.
 */
export class ApiError extends Error {
  constructor(status, code, message, fields = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields; // {fieldName: "message"} for validation errors
  }
}

export async function api(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json", "X-Requested-With": "stif-campus" };
  // Include the HttpOnly API session cookie for a separately hosted frontend.
  // The backend still accepts only configured CORS origins and CSRF headers.
  const init = { method, headers, credentials: "include" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(`${API}${path}`, init);
  } catch {
    throw new ApiError(0, "network", "Could not reach the server. Check your connection and try again.");
  }
  let data = null;
  try { data = await response.json(); } catch { /* empty or non-JSON body */ }
  if (!response.ok) {
    const e = data?.error;
    throw new ApiError(
      response.status,
      e?.code || "error",
      e?.message || (response.status >= 500 ? "Something went wrong on our side. Please try again." : "The request could not be completed."),
      e?.fields || {},
    );
  }
  return data;
}

export const qs = (params) => {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") p.set(k, v); });
  const s = p.toString();
  return s ? `?${s}` : "";
};
