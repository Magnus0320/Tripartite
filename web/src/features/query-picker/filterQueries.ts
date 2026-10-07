import type { QueryItem } from "../../api/client";

/**
 * The items matching the search text, in their original order. The text is split on
 * whitespace, and an item matches when every word occurs in its query_id or its query,
 * ignoring case. Blank text matches everything.
 */
export function filterQueries(items: readonly QueryItem[], text: string): QueryItem[] {
  const words = text.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) {
    return [...items];
  }
  return items.filter((item) => {
    const haystack = `${item.query_id}\n${item.query}`.toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
}
