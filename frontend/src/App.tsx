import { useEffect, useState } from "react";

import "./App.css";

type HealthStatus = "checking" | "online" | "offline";

interface HealthResponse {
  status: string;
  service: string;
  version: string;
  environment: string;
}

const apiBaseUrl = (
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");

function App() {
  const [healthStatus, setHealthStatus] = useState<HealthStatus>("checking");
  const [serviceName, setServiceName] = useState("FlightPulse API");
  const [healthError, setHealthError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function checkBackend(): Promise<void> {
      try {
        const response = await fetch(`${apiBaseUrl}/health`, {
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Health check failed with HTTP ${response.status}`);
        }

        const health = (await response.json()) as HealthResponse;
        if (health.status !== "ok") {
          throw new Error("The API reported an unhealthy status");
        }

        setServiceName(health.service);
        setHealthStatus("online");
      } catch (error: unknown) {
        if (!controller.signal.aborted) {
          setHealthError(
            error instanceof Error ? error.message : "Unexpected health check error",
          );
          setHealthStatus("offline");
        }
      }
    }

    void checkBackend();
    return () => controller.abort();
  }, []);

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="FlightPulse Live home">
          <span className="brand-mark" aria-hidden="true">
            FP
          </span>
          <span>FlightPulse</span>
          <span className="brand-live">LIVE</span>
        </a>
        <span className="topbar-label">AVIATION INTELLIGENCE</span>
      </header>

      <section className="hero" aria-labelledby="page-title">
        <div className="eyebrow">
          <span className="eyebrow-line" />
          FLIGHT OPERATIONS, IN FOCUS
        </div>
        <h1 id="page-title">
          See the bigger
          <br />
          <span>flight picture.</span>
        </h1>
        <p className="hero-copy">
          A clearer view of the signals shaping the journey. FlightPulse Live
          brings flight intelligence into one considered workspace.
        </p>
        <div className="service-card" aria-live="polite">
          <span
            className={`status-dot status-${healthStatus}`}
            aria-hidden="true"
          />
          <div className="service-copy">
            <span className="service-title">{serviceName}</span>
            <span className="service-detail">
              {healthStatus === "checking" && "Checking backend connection"}
              {healthStatus === "online" && "Connected and responding"}
              {healthStatus === "offline" && healthError}
            </span>
          </div>
          <span className={`status-label status-label-${healthStatus}`}>
            {healthStatus}
          </span>
        </div>
      </section>

      <footer className="footer">
        <span>FLIGHTPULSE LIVE</span>
        <span>BUILT FOR A MORE CONNECTED VIEW OF AVIATION</span>
      </footer>
    </main>
  );
}

export default App;
