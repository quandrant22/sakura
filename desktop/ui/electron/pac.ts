// PAC-скрипт для YOUTUBE_PROXY: через прокси идут только домены плеера YouTube,
// всё остальное (локальный API, медиасервер, сервер Сакуры) — напрямую.
export const YT_DOMAINS = ["youtube.com", "youtube-nocookie.com", "ytimg.com", "googlevideo.com", "ggpht.com"];

/** "http://host:port" | "socks5://host:port" → текст PAC; пусто — прокси не задан/неверный. */
export function pacFor(proxy: string): string {
  const m = /^(https?|socks5?):\/\/([^/\s]+)$/i.exec(proxy.trim());
  if (!m) return "";
  const kind = m[1]!.toLowerCase().startsWith("socks") ? "SOCKS5" : "PROXY";
  const cond = YT_DOMAINS.map((d) => `dnsDomainIs(host, ".${d}") || host === "${d}"`).join(" || ");
  return `function FindProxyForURL(url, host) { if (${cond}) return "${kind} ${m[2]}"; return "DIRECT"; }`;
}
