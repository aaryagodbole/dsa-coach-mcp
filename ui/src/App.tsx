import { useApp, useHostStyles } from "@modelcontextprotocol/ext-apps/react";
import { useState } from "react";
import { Calibration } from "./components/Calibration";
import { DueList } from "./components/DueList";
import type { OpenLink } from "./components/ExternalLink";
import { ForgettingForecast } from "./components/ForgettingForecast";
import { MistakeHeatmap } from "./components/MistakeHeatmap";
import { MistakeRecovery } from "./components/MistakeRecovery";
import { Overconfidence } from "./components/Overconfidence";
import { Platforms } from "./components/Platforms";
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

  if (error) return <p className="empty">Couldn't connect to the host: {error.message}</p>;
  if (!data) return <p className="empty">Waiting for data…</p>;
  const openLink: OpenLink = (url) => app?.openLink({ url });
  const { insights } = data;
  return (
    <main>
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
