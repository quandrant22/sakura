import { expect, test } from "vitest";

import { pacFor } from "./pac";

function route(pac: string, host: string): string {
  const dnsDomainIs = (h: string, d: string) => h.endsWith(d);
  const fn = new Function("dnsDomainIs", `${pac}; return FindProxyForURL;`)(dnsDomainIs) as (u: string, h: string) => string;
  return fn(`https://${host}/`, host);
}

test("через прокси только домены YouTube", () => {
  const pac = pacFor("http://10.0.0.1:3128");
  for (const h of ["www.youtube.com", "youtube.com", "i.ytimg.com", "rr1---sn-x.googlevideo.com", "yt3.ggpht.com"]) {
    expect(route(pac, h)).toBe("PROXY 10.0.0.1:3128");
  }
  for (const h of ["127.0.0.1", "example.com", "notyoutube.com", "music.yandex.ru"]) {
    expect(route(pac, h)).toBe("DIRECT");
  }
});

test("socks5 и неверные значения", () => {
  expect(route(pacFor("socks5://h:1080"), "www.youtube.com")).toBe("SOCKS5 h:1080");
  expect(pacFor("")).toBe("");
  expect(pacFor("ftp://x:1")).toBe("");
  expect(pacFor("http://h:1/path")).toBe("");
});
