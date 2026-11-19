import { useApp, useHostStyles } from "@modelcontextprotocol/ext-apps/react";
import { useState } from "react";
import { Accounts, type LinkProfile } from "./components/Accounts";
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
import { type Tab, Tabs } from "./components/Tabs";
import type { Dashboard } from "./types";

const TAB_KEY = "dsa-coach-tab";
const TAB_IDS = ["today", "skills", "insights"];

function rememberedTab(): string {
  try {
    const saved = localStorage.getItem(TAB_KEY);
    if (saved && TAB_IDS.includes(saved)) return saved;
  } catch {
    // Blocked storage: start on Today.
  }
  return "today";
}

export function App() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [tab, setTab] = useState<string>(rememberedTab);
  const selectTab = (id: string) => {
    setTab(id);
    try {
      localStorage.setItem(TAB_KEY, id);
    } catch {
      // Storage can be blocked in a sandboxed view; the tab just isn't remembered.
    }
  };
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
  // Hosts that let the view call the server's tools can link and import right here.
  const link: LinkProfile | null =
    app && app.getHostCapabilities()?.serverTools
      ? async (url) => {
          const text = (r: { content?: { type: string; text?: string }[] }) =>
            r.content?.find((c) => c.type === "text")?.text ?? "Something went wrong.";
          try {
            const linked = await app.callServerTool({
              name: "link_account",
              arguments: { handle: url },
            });
            if (linked.isError) return { ok: false, text: text(linked) };
            const account = linked.structuredContent as { platform: string; handle: string };
            const imported = await app.callServerTool({
              name: "import_solved",
              arguments: { platform: account.platform },
            });
            const counts = imported.structuredContent as { imported: number; due_now: number };
            const refreshed = await app.callServerTool({ name: "show_dashboard", arguments: {} });
            if (refreshed.structuredContent) {
              setData(refreshed.structuredContent as unknown as Dashboard);
            }
            const tail = imported.isError
              ? ` Couldn't import your solved problems: ${text(imported)}`
              : ` Imported ${counts.imported} solved problems; ${counts.due_now} due. ` +
                'Press "Plan my session" for problems picked for you.';
            return { ok: true, text: `Linked ${account.platform} as ${account.handle}.${tail}` };
          } catch (e) {
            return { ok: false, text: e instanceof Error ? e.message : String(e) };
          }
        }
      : null;
  const { insights } = data;
  const tabs: Tab[] = [
    { id: "today", label: "Today", badge: data.due.length },
    { id: "skills", label: "Skills" },
    { id: "insights", label: "Insights" },
  ];
  return (
    <main>
      <header className="brand">
        <div className="logo">DSA COACH</div>
        <span className="muted">{todayLabel(data.due.length, data.due_total ?? data.due.length)}</span>
      </header>
      <Tabs tabs={tabs} selected={tab} onSelect={selectTab}>
        {tab === "today" && (
          <>
            <Coach steps={data.next_steps ?? []} openLink={openLink} send={send} />
            <DueList due={data.due} total={data.due_total ?? data.due.length} openLink={openLink} />
            <Checklists checklists={data.checklists ?? []} />
          </>
        )}
        {tab === "skills" && (
          <>
            <SkillMap skills={data.skills ?? { tags: [], unreviewed: [] }} />
            <Accounts accounts={data.accounts ?? []} link={link} send={send} />
            <Platforms progress={data.progress} />
          </>
        )}
        {tab === "insights" && (
          <>
            <ForgettingForecast forecast={insights.forecast} days={insights.horizon_days} />
            <MistakeRecovery recovery={insights.recovery} />
            <Overconfidence reviews={insights.overconfidence} openLink={openLink} />
            <MistakeHeatmap patterns={data.patterns} />
            <Calibration bins={insights.calibration} />
          </>
        )}
      </Tabs>
    </main>
  );
}

function todayLabel(today: number, total: number): string {
  if (total === 0) return "nothing due today";
  const more = total - today;
  return more > 0 ? `${today} to revise today · ${more} more due` : `${today} to revise today`;
}
