import type { SkillMap as Skills } from "../types";
import { percent, recallColour } from "./format";

// Whole problems once there are enough of them; a decimal while a few reviews make it up.
const count = (n: number) => (n >= 10 ? String(Math.round(n)) : String(Math.round(n * 10) / 10));

export function SkillMap({ skills }: { skills: Skills }) {
  return (
    <section>
      <h2>What you still know</h2>
      <p className="sub">per topic: solved on your platforms, revised here, and how many you'd get right today</p>
      {skills.tags.length === 0 ? (
        <p className="empty">Review a few tagged problems to see what you still remember.</p>
      ) : (
        <div className="due">
          {skills.tags.map((t) => (
            <div className="row skill" key={t.tag}>
              <div>
                <div className="name">{t.tag}</div>
                <div className="muted">
                  {t.solved != null && <>{t.solved} solved · </>}
                  {t.reviewed} revised · <b>~{count(t.remembered)}</b> you'd get right today
                </div>
              </div>
              <div className="bar" title={`${percent(t.recall)} average recall`}>
                <span style={{ width: percent(t.recall), background: recallColour(t.recall) }} />
              </div>
              <div className="pct">{percent(t.recall)}</div>
            </div>
          ))}
        </div>
      )}
      {skills.unreviewed.length > 0 && (
        <div className="tags">
          <span className="tags-label">solved but never revised here</span>
          {skills.unreviewed.map((t) => (
            <span className="chip mid" key={t.tag}>
              {t.tag} <b>{t.count}</b>
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
