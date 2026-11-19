import { type KeyboardEvent, type ReactNode, useRef } from "react";

export type Tab = { id: string; label: string; badge?: number };

// An accessible tab bar (WAI-ARIA tabs pattern): arrow keys, Home and End move between
// tabs, and only the selected tab is in the page's tab order.
export function Tabs({
  tabs,
  selected,
  onSelect,
  children,
}: {
  tabs: Tab[];
  selected: string;
  onSelect: (id: string) => void;
  children: ReactNode;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = tabs.length - 1;
    const next =
      event.key === "ArrowRight" ? (index === last ? 0 : index + 1)
      : event.key === "ArrowLeft" ? (index === 0 ? last : index - 1)
      : event.key === "Home" ? 0
      : event.key === "End" ? last
      : null;
    if (next === null) return;
    event.preventDefault();
    onSelect(tabs[next].id);
    refs.current[tabs[next].id]?.focus();
  }

  return (
    <>
      <div className="tabs" role="tablist" aria-label="Dashboard sections">
        {tabs.map((tab, index) => {
          const active = tab.id === selected;
          return (
            <button
              key={tab.id}
              ref={(el) => {
                refs.current[tab.id] = el;
              }}
              type="button"
              role="tab"
              id={`tab-${tab.id}`}
              aria-selected={active}
              aria-controls={`panel-${tab.id}`}
              tabIndex={active ? 0 : -1}
              className={active ? "tab active" : "tab"}
              onClick={() => onSelect(tab.id)}
              onKeyDown={(e) => onKeyDown(e, index)}
            >
              {tab.label}
              {tab.badge ? <span className="badge">{tab.badge}</span> : null}
            </button>
          );
        })}
      </div>
      <div
        className="tabpanel"
        role="tabpanel"
        id={`panel-${selected}`}
        aria-labelledby={`tab-${selected}`}
      >
        {children}
      </div>
    </>
  );
}
