import { useState } from "react";
import type { NextStep } from "../types";
import { ExternalLink, type OpenLink } from "./ExternalLink";

export type SendMessage = (text: string) => Promise<boolean>;

// Short requests the assistant turns into a report, plan or quiz with dsa-coach's tools.
const ASKS = [
  {
    label: "Weekly report",
    text:
      "Using dsa-coach, give me my weekly DSA report: what I did this week, what is " +
      "slipping, which mistakes keep coming back, and three things to do next.",
  },
  {
    label: "Plan my session",
    text:
      "Using dsa-coach, plan my next practice session from my recurring mistakes and " +
      "weakest topics, with problems that target them.",
  },
  {
    label: "Quiz me",
    text: "Using dsa-coach, quiz me on my due revisions, one question at a time.",
  },
];

const ICON: Record<NextStep["kind"], string> = {
  revise: "↻",
  mistake: "!",
  topic: "◆",
  recheck: "?",
};

export function Coach({
  steps,
  openLink,
  send,
}: {
  steps: NextStep[];
  openLink: OpenLink;
  send: SendMessage | null;
}) {
  const [status, setStatus] = useState<{ label: string; ok: boolean } | null>(null);
  const [manual, setManual] = useState<string | null>(null);

  const ask = async (label: string, text: string) => {
    if (!send) {
      setManual(text);
      return;
    }
    const ok = await send(text);
    setStatus({ label, ok });
    if (!ok) setManual(text);
  };

  return (
    <section className="coach">
      <h2>Do this next</h2>
      <p className="sub">picked from your own reviews, mistakes and accounts</p>
      {steps.length === 0 ? (
        <p className="empty">Log a few reviews and link an account to get suggestions.</p>
      ) : (
        <ol className="steps">
          {steps.map((s) => (
            <li className={`step ${s.kind}`} key={s.kind}>
              <span className="icon" aria-hidden="true">
                {ICON[s.kind]}
              </span>
              <div>
                <div className="step-title">
                  {s.url ? <ExternalLink url={s.url} label={s.title} openLink={openLink} /> : s.title}
                </div>
                <div className="muted">{s.detail}</div>
              </div>
            </li>
          ))}
        </ol>
      )}
      <div className="asks">
        {ASKS.map((a) => (
          <button type="button" key={a.label} onClick={() => ask(a.label, a.text)}>
            {a.label}
          </button>
        ))}
      </div>
      {status && (
        <p className="muted" role="status">
          {status.ok ? `Asked your assistant for: ${status.label}.` : "The chat didn't take the message."}
        </p>
      )}
      {manual && (
        <div className="manual">
          <p className="muted">Paste this into your chat:</p>
          <code>{manual}</code>
        </div>
      )}
    </section>
  );
}
