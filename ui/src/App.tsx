import { useApp, useHostStyles } from "@modelcontextprotocol/ext-apps/react";
import { useState } from "react";
import { Accounts } from "./components/Accounts";
import { Calibration } from "./components/Calibration";
import { Checklists } from "./components/Checklists";
import { Coach, type SendMessage } from "./components/Coach";
import { DueList } from "./components/DueList";
import type { OpenLink } from "./components/ExternalLink";
import { ForgettingForecast } from "./components/ForgettingForecast";
import { MistakeHeatmap } from "./components/MistakeHeatmap";
import { MistakeRecovery } from "./components/MistakeRecovery";
import { Overconfidence } from "./components/Overconfidence";
import { Platforms } from "./components/Platforms";
import { SkillMap } from "./components/SkillMap";
import type { Dashboard } from "./types";

export function App() {
  const [data, setData] = useState<Dashboard | null>(null);
  const { app, error } = useApp({
    appInfo: { name: "dsa-coach-dashboard", version: "2" },
    capabilities: {},
    onAppCreated: (created) => {
      created.ontoolresult = (result) => {
        if (result.structuredContent) setData(result.structuredContent as unknown as Dashboard);
      };
    },
  });
  useHostStyles(app, app?.getHostContext());

  if (error) return <p className="status empty">Couldn't connect to the host: {error.message}</p>;
  if (!data) return <p className="status empty">Waiting for data…</p>;
  const openLink: OpenLink = (url) => app?.openLink({ url });
  // Only hosts that accept messages from the view can take a request into the chat.
  const send: SendMessage | null = app?.getHostCapabilities()?.message
    ? async (text) => {
        try {
          const result = await app.sendMessage({ role: "user", content: [{ type: "text", text }] });
          return !result.isError;
        } catch {
          return false;
        }
      }
    : null;
  const { insights } = data;
  return (
    <main>
      <header className="brand">
        <div className="logo">DSA COACH</div>
        <span className="muted">{data.due.length} due now</span>
      </header>
      <Coach steps={data.next_steps ?? []} openLink={openLink} send={send} />
      <SkillMap skills={data.skills ?? { tags: [], unreviewed: [] }} />
      <Accounts accounts={data.accounts ?? []} />
      <Checklists checklists={data.checklists ?? []} />
      <Platforms progress={data.progress} />
      <ForgettingForecast forecast={insights.forecast} days={insights.horizon_days} />
      <DueList due={data.due} openLink={openLink} />
      <MistakeRecovery recovery={insights.recovery} />
      <Overconfidence reviews={insights.overconfidence} openLink={openLink} />
      <MistakeHeatmap patterns={data.patterns} />
      <Calibration bins={insights.calibration} />
    </main>
  );
}
