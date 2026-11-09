import { useState } from "react";
import type { ReviewCard } from "../types";

type OpenLink = (url: string) => Promise<{ isError?: boolean }> | undefined;

const riskColour = (r: number) => (r < 0.7 ? "var(--risk)" : r < 0.85 ? "var(--accent)" : "var(--ok)");
const isWebUrl = (url: string) => /^https?:\/\//.test(url);

export function DueList({ due, openLink }: { due: ReviewCard[]; openLink: OpenLink }) {
  return (
    <section>
      <h2>Due now · chance you still remember it</h2>
      {due.length === 0 && <p className="empty">Nothing due. Nice.</p>}
      <div className="due">
        {due.map((card) => (
          <DueRow key={`${card.platform}/${card.problem_id}`} card={card} openLink={openLink} />
        ))}
      </div>
    </section>
  );
}

function DueRow({ card, openLink }: { card: ReviewCard; openLink: OpenLink }) {
  const [linkFailed, setLinkFailed] = useState(false);
  const r = card.retrievability ?? 0;
  const label = `${card.title} · ${card.platform}`;

  // Sandboxed views may not open windows themselves, so the host opens the link.
  const open = async (event: React.MouseEvent) => {
    event.preventDefault();
    if (!isWebUrl(card.url)) return;
    try {
      const result = await openLink(card.url);
      if (!result || result.isError) setLinkFailed(true);
    } catch {
      setLinkFailed(true);
    }
  };

  return (
    <div className="row">
      <a href={isWebUrl(card.url) ? card.url : "#"} title={label} onClick={open}>
        {label}
      </a>
      <div className="bar">
        <span style={{ width: `${Math.round(r * 100)}%`, background: riskColour(r) }} />
      </div>
      <div className="pct">{card.retrievability == null ? "new" : `${Math.round(r * 100)}%`}</div>
      {linkFailed && (
        // Leave the address visible so the user can still open it themselves.
        <div className="note empty">Couldn't open this link: {card.url}</div>
      )}
    </div>
  );
}
