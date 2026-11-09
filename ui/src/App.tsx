import { useApp, useHostStyles } from "@modelcontextprotocol/ext-apps/react";
import { useState } from "react";
import { DueList } from "./components/DueList";
import { MistakeHeatmap } from "./components/MistakeHeatmap";
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
  return (
    <main>
      <Platforms progress={data.progress} />
      <DueList due={data.due} openLink={(url) => app?.openLink({ url })} />
      <MistakeHeatmap patterns={data.patterns} />
    </main>
  );
}
