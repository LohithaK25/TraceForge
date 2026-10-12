import { useEffect, useState } from "react";

import { getApiHealth, type ApiHealth } from "./api/health";
import { IncidentDashboard } from "./components/IncidentDashboard";
import { HealthStatus } from "./components/HealthStatus";

type ConnectionState = "loading" | "ready" | "unavailable";

export default function App() {
  const [connectionState, setConnectionState] = useState<ConnectionState>("loading");
  const [health, setHealth] = useState<ApiHealth>();

  useEffect(() => {
    const controller = new AbortController();
    getApiHealth(controller.signal)
      .then((result) => {
        setHealth(result);
        setConnectionState("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setConnectionState("unavailable");
      });

    return () => controller.abort();
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Workspace navigation">
        <a className="brand" href="#overview" aria-label="TraceForge overview">
          <span className="brand-mark" aria-hidden="true">T</span>
          <span>TraceForge</span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <nav>
          <a className="nav-link nav-link--active" href="#overview" aria-current="page">
            <span className="nav-icon" aria-hidden="true">◫</span> Overview
          </a>
        </nav>
        <div className="sidebar-foot">
          <span className="environment-dot" aria-hidden="true" />
          <span>Local environment</span>
        </div>
      </aside>

      <main id="overview" className="main-content">
        <header className="topbar">
          <div className="breadcrumb"><span>TraceForge</span><span aria-hidden="true">/</span><strong>Overview</strong></div>
          <span className="local-badge"><span aria-hidden="true" /> LOCAL</span>
        </header>

        <div className="page-content">
          <section className="page-heading" aria-labelledby="page-title">
            <div>
              <p className="eyebrow">INCIDENT RESPONSE</p>
              <h1 id="page-title">Overview</h1>
              <p className="subtitle">API-backed incidents, persisted service observations, and collection freshness.</p>
            </div>
            <div className="date-chip"><span className="calendar-icon" aria-hidden="true">▦</span> API data</div>
          </section>

          <section className="connection-card" aria-labelledby="connection-title">
            <div className="connection-copy">
              <span className="section-kicker">PLATFORM CONNECTION</span>
              <h2 id="connection-title">Investigation API</h2>
              <p>The dashboard reads live status from the TraceForge gateway.</p>
            </div>
            <HealthStatus state={connectionState} health={health} />
          </section>

          <section className="signals-section" aria-labelledby="signals-title">
            <div className="section-heading">
              <div>
                <span className="section-kicker">INVESTIGATION SERVICE</span>
                <h2 id="signals-title">Incident activity</h2>
              </div>
              <span className="data-label">LIVE API DATA</span>
            </div>
            <IncidentDashboard />
          </section>

          <footer className="page-footer">
            <span>Evidence first. AI second.</span>
            <span>TraceForge <span className="footer-separator">·</span> Local development</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
