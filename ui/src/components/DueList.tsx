import type { ReviewCard } from "../types";
import { ExternalLink, type OpenLink } from "./ExternalLink";
import { percent, recallColour } from "./format";

export function DueList({
  due,
  total,
  openLink,
}: {
  due: ReviewCard[];
  total: number;
  openLink: OpenLink;
}) {
  const more = total - due.length;
  return (
    <section>
      <h2>Today</h2>
      <p className="sub">
        the revisions you're most likely to forget, with the chance you still remember each
        {more > 0 && `; ${more} more are due and come up on later days`}
      </p>
      {due.length === 0 && <p className="empty">Nothing due. Nice.</p>}
      <div className="due">
        {due.map((card) => {
          const chance = card.recall ?? card.retrievability;
          const r = chance ?? 0;
          return (
            <div className="row" key={`${card.platform}/${card.problem_id}`}>
              <ExternalLink url={card.url} label={`${card.title} · ${card.platform}`} openLink={openLink} />
              <div className="bar">
                <span style={{ width: percent(r), background: recallColour(r) }} />
              </div>
              <div className="pct">{chance == null ? "new" : percent(r)}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
