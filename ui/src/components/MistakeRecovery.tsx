import type { MistakeRecovery as Recovery } from "../types";
import { day } from "./format";

export function MistakeRecovery({ recovery }: { recovery: Recovery[] }) {
  return (
    <section>
      <h2>Mistake recovery · reviews of those problems since it last happened</h2>
      {recovery.length === 0 && <p className="empty">No mistakes journaled yet.</p>}
      <div className="due">
        {recovery.map((m) => (
          <div className="row recovery" key={m.kind}>
            <span className="name">{m.kind}</span>
            <span className="muted">
              {m.times}× · last {day(m.last_seen)}
            </span>
            <span className={`pill ${m.clean_reviews_since === 0 ? "risk" : "ok"}`}>
              {m.clean_reviews_since} clean
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
