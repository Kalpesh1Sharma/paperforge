export type DiffWindow = { before: string; after: string; truncated: boolean };
const plainText = (html: string | null) => {
  const document = new DOMParser().parseFromString(html ?? "", "text/html");
  return (document.body.textContent ?? "").replace(/\s+/g, " ").trim();
};
export const changeWindow = (oldHtml: string | null, newHtml: string | null): DiffWindow => {
  const oldText = plainText(oldHtml); const newText = plainText(newHtml);
  let start = 0; while (start < oldText.length && start < newText.length && oldText[start] === newText[start]) start++;
  let oldEnd = oldText.length - 1; let newEnd = newText.length - 1;
  while (oldEnd >= start && newEnd >= start && oldText[oldEnd] === newText[newEnd]) { oldEnd--; newEnd--; }
  const radius = 260; const from = Math.max(0, start - radius); const oldTo = Math.min(oldText.length, oldEnd + radius + 1); const newTo = Math.min(newText.length, newEnd + radius + 1);
  return { before: oldText.slice(from, oldTo), after: newText.slice(from, newTo), truncated: from > 0 || oldTo < oldText.length || newTo < newText.length };
};
