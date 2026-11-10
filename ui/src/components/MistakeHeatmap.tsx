import type { MistakePatterns } from "../types";

export function MistakeHeatmap({ patterns }: { patterns: MistakePatterns }) {
  if (patterns.kinds.length === 0) {
    return (
      <section>
        <h2>Mistakes</h2>
        <p className="sub">by label and problem tag</p>
        <p className="empty">No mistakes journaled yet.</p>
      </section>
    );
  }
  // Every label shows its total; tag columns only appear for tagged problems, so a
  // journal of untagged mistakes still shows up.
  const cells = patterns.by_tag;
  const tags = [...new Set(cells.map((c) => c.key))];
  const count = new Map(cells.map((c) => [`${c.kind}\u0000${c.key}`, c.count]));
  const max = Math.max(1, ...cells.map((c) => c.count));

  return (
    <section>
      <h2>Mistakes</h2>
      <p className="sub">by label and problem tag</p>
      <div className="scroll">
        <table>
          <thead>
            <tr>
              <th><span className="sr-only">label</span></th>
              <th>total</th>
              {tags.map((t) => <th key={t}>{t}</th>)}
            </tr>
          </thead>
          <tbody>
            {patterns.kinds.map(({ kind, count: total }) => (
              <tr key={kind}>
                <th className="kind">{kind}</th>
                <td>{total}</td>
                {tags.map((t) => {
                  const n = count.get(`${kind}\u0000${t}`) ?? 0;
                  return (
                    <td key={t} style={n ? { background: `rgba(var(--heat), ${0.15 + (0.85 * n) / max})` } : undefined}>
                      {n || ""}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
