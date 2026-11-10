import type { OverconfidentReview } from "../types";
import { ExternalLink, type OpenLink } from "./ExternalLink";
import { day } from "./format";

export function Overconfidence({ reviews, openLink }: { reviews: OverconfidentReview[]; openLink: OpenLink }) {
  return (
    <section>
      <h2>Overconfidence</h2>
      <p className="sub">rated easy, then failed at the next review</p>
      {reviews.length === 0 && <p className="empty">None so far.</p>}
      <div className="due">
        {reviews.map((r) => (
          <div className="row recovery" key={`${r.platform}/${r.problem_id}/${r.forgot_at}`}>
            <ExternalLink url={r.url} label={`${r.title} · ${r.platform}`} openLink={openLink} />
            <span className="muted">easy {day(r.rated_easy_at)}</span>
            <span className="pill risk">failed {day(r.forgot_at)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
