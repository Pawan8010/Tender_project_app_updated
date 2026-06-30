import { Clock3 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, clearToken, getRefreshToken, setTokens } from "../lib/api.js";

function format(seconds) {
  if (seconds === null) return "--:--";
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

export default function SessionTimer({ onExpired }) {
  const [remaining, setRemaining] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const onExpiredRef = useRef(onExpired);

  useEffect(() => {
    onExpiredRef.current = onExpired;
  }, [onExpired]);

  async function refreshSession() {
    const refreshToken = getRefreshToken();
    if (!refreshToken) {
      clearToken();
      onExpiredRef.current?.();
      return;
    }
    setRefreshing(true);
    try {
      const data = await api("/auth/refresh", {
        method: "POST",
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      setTokens(data.access_token, data.refresh_token);
      const info = await api("/users/me/session-info");
      setRemaining(info.remaining_seconds);
    } catch {
      clearToken();
      onExpiredRef.current?.();
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    let active = true;
    api("/users/me/session-info")
      .then((data) => active && setRemaining(data.remaining_seconds))
      .catch(() => {
        clearToken();
        onExpiredRef.current?.();
      });
    const timer = window.setInterval(() => {
      setRemaining((value) => {
        if (value === null) return value;
        if (value === 120) {
          refreshSession();
        }
        if (value <= 1) {
          clearToken();
          onExpiredRef.current?.();
          return 0;
        }
        return value - 1;
      });
    }, 1000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <span className={`sessionTimer ${remaining !== null && remaining < 300 ? "warning" : ""}`} title="Session time remaining">
      <Clock3 size={15} />
      {refreshing ? "refreshing" : format(remaining)}
    </span>
  );
}
