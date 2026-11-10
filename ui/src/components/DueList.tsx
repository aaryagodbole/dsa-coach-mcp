import type { ReviewCard } from "../types";
import { ExternalLink, type OpenLink } from "./ExternalLink";
import { percent, recallColour } from "./format";

export function DueList({ due, openLink }: { due: ReviewCard[]; openLink: OpenLink }) {
  return (
    <section>
      <h2>Due now</h2>
      <p className="sub">chance you still remember it</p>
      {due.length === 0 && <p className="empty">Nothing due. Nice.</p>}
      <div className="due">
        {due.map((card) => {
          const r = card.retrievability ?? 0;
          return (
            <div className="row" key={`${card.platform}/${card.problem_id}`}>
              <ExternalLink url={card.url} label={`${card.title} · ${card.platform}`} openLink={openLink} />
              <div className="bar">
                <span style={{ width: percent(r), background: recallColour(r) }} />
              </div>
              <div className="pct">{card.retrievability == null ? "new" : percent(r)}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
