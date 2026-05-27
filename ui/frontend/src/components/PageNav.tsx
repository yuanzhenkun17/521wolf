import type { GamePage } from "../gamePages";

export function PageNav({
  pages,
  selectedPageId,
  onSelectPage,
}: {
  pages: GamePage[];
  selectedPageId: string;
  onSelectPage: (pageId: string) => void;
}) {
  return (
    <div className="border-b border-border bg-muted/30 px-4 py-3">
      <div className="flex gap-2 overflow-x-auto pb-1">
        {pages.map((page) => (
          <button
            key={page.id}
            className={
              page.id === selectedPageId
                ? "shrink-0 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
                : "shrink-0 rounded-md border border-border bg-card px-3 py-2 text-sm hover:bg-muted"
            }
            onClick={() => onSelectPage(page.id)}
          >
            {page.label}
          </button>
        ))}
      </div>
    </div>
  );
}
