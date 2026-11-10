import type { AccountStats, TagCount } from "../types";

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

export function Accounts({ accounts }: { accounts: AccountStats[] }) {
  return (
    <section>
      <h2>My platforms</h2>
      <p className="sub">live stats from the accounts you linked</p>
      {accounts.length === 0 ? (
        <p className="empty">
          No accounts linked yet. Tell your assistant your username, e.g. "link my LeetCode
          account, I'm alice".
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
