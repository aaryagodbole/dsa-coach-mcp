import { useState, type ReactNode } from "react";

export type OpenLink = (url: string) => Promise<{ isError?: boolean }> | undefined;

const isWebUrl = (url: string) => /^https?:\/\//.test(url);

// Sandboxed views may not open windows themselves, so the host opens the link.
export function ExternalLink({ url, label, openLink }: { url: string; label: string; openLink: OpenLink }) {
  const [failed, setFailed] = useState(false);

  const open = async (event: React.MouseEvent) => {
    event.preventDefault();
    if (!isWebUrl(url)) return;
    try {
      const result = await openLink(url);
      if (!result || result.isError) setFailed(true);
    } catch {
      setFailed(true);
    }
  };

  return (
    <>
      <a href={isWebUrl(url) ? url : "#"} title={label} onClick={open}>
        {label}
      </a>
      {failed && <LinkFailed url={url} />}
    </>
  );
}

// Leave the address visible so the user can still open it themselves.
function LinkFailed({ url }: { url: string }): ReactNode {
  return <div className="note empty">Couldn't open this link: {url}</div>;
}
