import type { TagChecklist } from "../types";
import { day } from "./format";

export function Checklists({ checklists }: { checklists: TagChecklist[] }) {
  return (
    <section>
      <h2>Before you submit</h2>
      <p className="sub">your own past mistakes per topic: tick them off before you hit submit</p>
      {checklists.length === 0 ? (
        <p className="empty">Log mistakes on tagged problems to build your checklists.</p>
      ) : (
        <div className="grid checklists">
          {checklists.map((c) => (
            <div className="card checklist" key={c.tag}>
              <div className="tag">{c.tag}</div>
              <ul>
                {c.items.map((i) => (
                  <li key={i.kind}>
                    <label>
                      <input type="checkbox" />
                      <span>
                        <span className="kind">{i.kind}</span>
                        <span className="muted meta">
                          {i.times}× · last {day(i.last_seen)}
                        </span>
                        <span className="note">{i.note}</span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
