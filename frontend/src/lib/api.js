const API_URL = import.meta.env.VITE_API_URL || "/api";

export function apiUrl(path) {
  return `${API_URL}${path}`;
}

export function getToken() {
  return localStorage.getItem("tender_token");
}

export function setToken(token) {
  localStorage.setItem("tender_token", token);
}

export function getRefreshToken() {
  return localStorage.getItem("tender_refresh_token");
}

export function setRefreshToken(token) {
  if (token) localStorage.setItem("tender_refresh_token", token);
}

export function setTokens(accessToken, refreshToken) {
  setToken(accessToken);
  setRefreshToken(refreshToken);
  window.dispatchEvent(new CustomEvent("auth-token-updated"));
}

export function clearToken() {
  localStorage.removeItem("tender_token");
  localStorage.removeItem("tender_refresh_token");
  window.dispatchEvent(new CustomEvent("auth-token-cleared"));
}

async function refreshAccessToken() {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;
  const response = await fetch(apiUrl("/auth/refresh"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!response.ok) {
    clearToken();
    return null;
  }
  const data = await response.json();
  setTokens(data.access_token, data.refresh_token);
  return data.access_token;
}

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  let response = await fetch(apiUrl(path), { ...options, headers });
  if (response.status === 401 && path !== "/auth/refresh" && getRefreshToken()) {
    const nextToken = await refreshAccessToken();
    if (nextToken) {
      headers.set("Authorization", `Bearer ${nextToken}`);
      response = await fetch(apiUrl(path), { ...options, headers });
    }
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
      if (Array.isArray(detail)) {
        detail = detail.map((item) => item.msg || item.message || String(item)).join(", ");
      }
    } catch {
      // Keep HTTP status text when response is not JSON.
    }
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

export function exportUrl(format, params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value);
  });
  return apiUrl(`/export/${format}?${query.toString()}`);
}
