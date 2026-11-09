import type { PlatformProgress } from "../types";

export function Platforms({ progress }: { progress: PlatformProgress[] }) {
  return (
    <section>
      <h2>Platforms</h2>
      {progress.length === 0 && <p className="empty">No reviews yet.</p>}
      <div className="grid">
        {progress.map((p) => (
          <div className="card" key={p.platform}>
            <div className="name">{p.platform}</div>
            <div className="tag">
              {p.source === "reported" ? "recorded from pages" : "from the platform's API"}
            </div>
            <div className="stats">
              <div><b>{p.problems}</b>problems</div>
              <div><b>{p.reviews}</b>reviews</div>
              <div><b>{p.due_now}</b>due</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
