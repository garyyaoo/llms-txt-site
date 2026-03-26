import { useState, useRef, useEffect } from "react";
import "./App.css";

function CogIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function StepIcon({ state }) {
  return (
    <span className={`step-icon step-icon--${state}`}>
      {state === "done" && (
        <svg className="step-check" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="2,6 5,9 10,3" />
        </svg>
      )}
    </span>
  );
}

export default function App() {
  const [url, setUrl] = useState("");
  const [crawl, setCrawl] = useState(true);
  const [useLlm, setUseLlm] = useState(true);
  const [maxScrape, setMaxScrape] = useState(100);
  const [maxDiscoveryTime, setMaxDiscoveryTime] = useState(30);
  const [maxDepth, setMaxDepth] = useState(3);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const [submitted, setSubmitted] = useState(false);
  const [phase, setPhase] = useState(null);
  const [discoveredUrls, setDiscoveredUrls] = useState([]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const esRef = useRef(null);
  const urlListRef = useRef(null);

  useEffect(() => {
    const el = urlListRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [discoveredUrls]);

  function handleReset() {
    if (esRef.current) esRef.current.close();
    setSubmitted(false);
    setPhase(null);
    setDiscoveredUrls([]);
    setResult(null);
    setError(null);
  }

  function handleSubmit(e) {
    e.preventDefault();
    if (esRef.current) esRef.current.close();

    setSubmitted(true);
    setPhase("discovery");
    setDiscoveredUrls([]);
    setResult(null);
    setError(null);

    const params = new URLSearchParams({ url, crawl, llm: useLlm, max_scrape: maxScrape, max_urls: maxScrape, max_discovery_time: maxDiscoveryTime, max_depth: maxDepth });

    const es = new EventSource(`/stream?${params}`);
    esRef.current = es;

    es.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "discovery") {
        setDiscoveredUrls((prev) => [...prev, msg.url]);
      } else if (msg.type === "phase") {
        setPhase(msg.name);
      } else if (msg.type === "done") {
        setResult(msg);
        setPhase("done");
        es.close();
      } else if (msg.type === "error") {
        setError(msg.message);
        setPhase("error");
        es.close();
      }
    };

    es.onerror = () => {
      setError("Connection lost");
      setPhase("error");
      es.close();
    };
  }

  const loading = phase === "discovery" || phase === "generating";
  const compact = submitted;

  const step1State = phase === null ? "idle" : phase === "discovery" ? "active" : "done";
  const step2State = phase === null || phase === "discovery" ? "idle" : phase === "generating" ? "active" : "done";
  const step3State = result ? "done" : "idle";

  return (
    <div className={`app${compact ? " app--compact" : ""}`}>
      <header className="hero">
        <h1 className="hero-title">LLMs.txt Generator</h1>
      </header>

      <ol className="hero-steps">
        <li><span className="hero-step-num">1</span>Enter any website</li>
        <li><span className="hero-step-num">2</span>Generate your llms.txt</li>
      </ol>

      <form onSubmit={handleSubmit} className="form">
        <div className="url-row">
          <input
            className="url-input"
            type="text"
            placeholder="https://example.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
            disabled={loading}
          />
          <button
            type="button"
            className={`btn-cog ${settingsOpen ? "active" : ""}`}
            onClick={() => setSettingsOpen((o) => !o)}
            aria-label="Settings"
            disabled={loading}
          >
            <CogIcon />
          </button>
          {phase === "done" ? (
            <button type="button" className="btn-generate" onClick={handleReset}>
              Try Another
            </button>
          ) : (
            <button type="submit" className="btn-generate" disabled={loading || !url.trim()}>
              {loading ? "Generating…" : "Generate"}
            </button>
          )}
        </div>

        <div className={`drawer ${settingsOpen ? "drawer--open" : ""}`}>
          <label className="toggle">
            <input type="checkbox" checked={crawl} onChange={(e) => setCrawl(e.target.checked)} disabled={loading} />
            <span className="toggle-label">Force crawl</span>
            <span className="toggle-hint">BFS nav crawler instead of sitemap</span>
          </label>
          <label className="toggle">
            <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} disabled={loading} />
            <span className="toggle-label">LLM mode</span>
            <span className="toggle-hint">Use Gemini instead of rule-based grouper</span>
          </label>
          <label className="num-field">
            <span className="num-label">Max discovery time (s)</span>
            <input type="number" min={5} max={300} value={maxDiscoveryTime}
              onChange={(e) => setMaxDiscoveryTime(e.target.value)} disabled={loading} />
          </label>
          <label className="num-field">
            <span className="num-label">Crawl depth</span>
            <input type="number" min={1} max={10} value={maxDepth}
              onChange={(e) => setMaxDepth(e.target.value)} disabled={loading} />
          </label>
          <label className="num-field">
            <span className="num-label">Max scrape</span>
            <input type="number" min={1} max={500} value={maxScrape}
              onChange={(e) => setMaxScrape(e.target.value)} disabled={loading} />
          </label>
        </div>
      </form>

      <div className="steps-section">
        {phase === "error" && <div className="error">{error}</div>}

        <div className="progress-card">
          <div className="progress-header">
            <div className="progress-header-left">
              <StepIcon state={step1State} />
              <span className="progress-title">Step 1: Discover URLs</span>
            </div>
            {discoveredUrls.length > 0 && (
              <span className="progress-badge">
                {discoveredUrls.length} URL{discoveredUrls.length !== 1 ? "s" : ""}
                {phase === "discovery" && <span className="dot-pulse" />}
              </span>
            )}
          </div>
          {discoveredUrls.length > 0 ? (
            <ul className="url-list" ref={urlListRef}>
              {discoveredUrls.map((u, i) => (
                <li key={i} className="url-item">{u}</li>
              ))}
            </ul>
          ) : (
            <div className="output-empty">Discovered URLs will appear here</div>
          )}
        </div>

        <div className="result">
          <div className="result-header">
            <div className="progress-header-left">
              <StepIcon state={step2State} />
              <h2>Step 2: Generate LLMs.txt</h2>
            </div>
            {result && (
              <button className="btn-copy" onClick={() => navigator.clipboard.writeText(result.llms_txt)}>
                Copy
              </button>
            )}
          </div>
          {result ? (
            <pre className="output">{result.llms_txt}</pre>
          ) : (
            <div className="output-empty">Generating…</div>
          )}
        </div>

        <div className="result">
          <div className="result-header">
            <div className="progress-header-left">
              <StepIcon state={step3State} />
              <h2>Generation Insights</h2>
            </div>
          </div>
          {result?.insights ? (
            <pre className="output insights-output">
              {result.insights.type === "llm"
                ? (result.insights.why || "No reasoning provided.")
                : result.insights.sections.map((s) =>
                    `## ${s.name}  [score:${s.score}  urls:${s.urls.length}]\n` +
                    s.urls.map((e) =>
                      `  [score:${e.score}]  ${e.title}\n  ${e.url}`
                    ).join("\n")
                  ).join("\n\n")}
            </pre>
          ) : (
            <div className="output-empty">Insights will appear here</div>
          )}
        </div>
      </div>
    </div>
  );
}
