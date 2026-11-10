import type { TopicForecast } from "../types";
import { percent, recallColour } from "./format";

export function ForgettingForecast({ forecast, days }: { forecast: TopicForecast[]; days: number }) {
  return (
    <section>
      <h2>Forgetting forecast</h2>
      <p className="sub">recall per tag now → in {days} days without revising</p>
      {forecast.length === 0 && <p className="empty">Review tagged problems to see this.</p>}
      <div className="due">
        {forecast.map((t) => (
          <div className="row forecast" key={t.tag}>
            <span title={`${t.problems} problem${t.problems === 1 ? "" : "s"}`}>
              {t.tag} <span className="muted">· {t.problems}</span>
            </span>
            <div className="bar stacked">
              <span style={{ width: percent(t.recall_now), background: "var(--line-strong)" }} />
              <span
                className="later"
                style={{ width: percent(t.recall_later), background: recallColour(t.recall_later) }}
              />
            </div>
            <div className="pct">
              {percent(t.recall_now)} → <b style={{ color: recallColour(t.recall_later) }}>{percent(t.recall_later)}</b>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
