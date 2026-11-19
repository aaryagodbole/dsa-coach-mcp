import { useState } from "react";
import type { AccountStats, TagCount } from "../types";
import type { SendMessage } from "./Coach";

// Links a pasted profile and imports its solved problems; resolves to what to tell the user.
export type LinkProfile = (url: string) => Promise<{ ok: boolean; text: string }>;

function linkRequest(url: string): string {
  return (
    `Using dsa-coach, link my profile ${url}, import the problems I already solved there, ` +
    "and suggest problems for my weakest topics."
  );
}

function PasteProfile({ link, send }: { link: LinkProfile | null; send: SendMessage | null }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [manual, setManual] = useState<string | null>(null);

  // A button, not a form: hosts sandbox the view without allow-forms, which blocks submit.
  async function submit() {
    const pasted = url.trim();
    if (!pasted || busy) return;
    setBusy(true);
    setStatus(null);
    setManual(null);
    try {
      if (link) {
        const result = await link(pasted);
        setStatus(result);
        if (result.ok) setUrl("");
      } else if (send && (await send(linkRequest(pasted)))) {
        setStatus({ ok: true, text: "Sent to your assistant." });
        setUrl("");
      } else {
        setManual(linkRequest(pasted));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="paste">
      <label htmlFor="profile-url">Paste your LeetCode or Codeforces profile link</label>
      <div className="paste-row">
        <input
          id="profile-url"
          type="text"
          inputMode="url"
          placeholder="https://leetcode.com/u/your-name/"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void submit();
          }}
          disabled={busy}
        />
        <button type="button" onClick={() => void submit()} disabled={busy || !url.trim()}>
          {busy ? "Linking…" : "Link"}
        </button>
      </div>
      {status && (
        <p className={status.ok ? "paste-ok" : "paste-err"} role="status">
          {status.text}
        </p>
      )}
      {manual && (
        <div className="manual">
          <p className="muted">This host can't link it from here. Ask your assistant:</p>
          <code>{manual}</code>
        </div>
      )}
    </div>
  );
}

function Tags({ label, tags, tone }: { label: string; tags: TagCount[]; tone: string }) {
  if (tags.length === 0) return null;
  return (
    <div className="tags">
      <span className="tags-label">{label}</span>
      {tags.map((t) => (
        <span className={`chip ${tone}`} key={t.tag}>
          {t.tag} <b>{t.count}</b>
        </span>
      ))}
    </div>
  );
}

function Account({ account }: { account: AccountStats }) {
  const levels = Object.entries(account.levels);
  return (
    <div className="card account">
      <div className="tag">{account.platform}</div>
      <div className="name">{account.handle}</div>
      {account.error ? (
        <p className="empty">Couldn't read this account: {account.error}</p>
      ) : (
        <>
          {levels.length > 0 && (
            <div className="stats">
              {levels.map(([level, n]) => (
                <div key={level}>
                  <b>{n}</b>
                  {level.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase()}
                </div>
              ))}
            </div>
          )}
          <Tags label="strongest" tags={account.strongest} tone="ok" />
          <Tags label="tried, not solved" tags={account.struggling} tone="risk" />
          <Tags label="barely practised" tags={account.least_practised} tone="mid" />
          {account.limitations.map((l) => (
            <p className="muted limit" key={l}>
              {l}
            </p>
          ))}
        </>
      )}
    </div>
  );
}

export function Accounts({
  accounts,
  link,
  send,
}: {
  accounts: AccountStats[];
  link: LinkProfile | null;
  send: SendMessage | null;
}) {
  return (
    <section>
      <h2>My platforms</h2>
      <p className="sub">live stats from the accounts you linked</p>
      <PasteProfile link={link} send={send} />
      {accounts.length === 0 ? (
        <p className="empty">
          No accounts linked yet. Paste your profile link above, or tell your assistant your
          username.
        </p>
      ) : (
        <div className="grid accounts">
          {accounts.map((a) => (
            <Account account={a} key={a.platform} />
          ))}
        </div>
      )}
    </section>
  );
}
