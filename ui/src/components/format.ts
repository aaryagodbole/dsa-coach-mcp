export const percent = (value: number) => `${Math.round(value * 100)}%`;

export const recallColour = (r: number) => (r < 0.7 ? "var(--risk)" : r < 0.85 ? "var(--accent)" : "var(--ok)");

export const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
