"""Гравюры и фото для «Сказания»: скачивание из открытых коллекций и обработка.

Источники — только public domain:
  * Art Institute of Chicago (api.artic.edu, IIIF; поле is_public_domain);
  * Wikimedia Commons (лицензия из extmetadata: Public domain / CC0).
Все авторы умерли до 1956 года — работы свободны и в России (жизнь + 70 лет),
и в Японии; «Кумои-дзакура» Ёсиды издана в 1926 году — свободна и в США.

Оригиналы ложатся в кэш вне репозитория (~/.cache/sakura-legend-art/raw/<ключ>/),
каждый в свою папку. Из них строятся:
  site/media/images/art/<ключ>-plate.jpg  — «пластина» для свитка: почти без правки,
                                             как репродукция в артбуке;
  site/media/images/art/<ключ>-bg.jpg     — тёмный фон раздела в гамме сайта;
  ~/.cache/sakura-legend-art/video/…      — исходники роликов 2400 px и вырезанный ворон;
  site/media/images/art/scroll-paper.jpg  — бумага свитков с едва видной каллиграфией.

Читает недоверенные файлы — запускать изолированно:
    python -I site/tools/fetch_art.py            # скачать недостающее и обработать
    python -I site/tools/fetch_art.py --offline  # только обработать то, что в кэше
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I не добавляет папку скрипта

from PIL import Image  # noqa: E402

import legend_common as L  # noqa: E402

Image.MAX_IMAGE_PIXELS = 60_000_000
CACHE = Path.home() / ".cache" / "sakura-legend-art"
RAW, VIDEO_SRC, FONTS = CACHE / "raw", CACHE / "video", CACHE / "fonts"
ART_DIR = L.IMAGES_DIR / "art"
UA = {"User-Agent": "legend-art-fetch/1.0 (public-domain image downloader)"}

# crop — доля кадра (x0, y0, x1, y1) без полей и подписей; bg/video — кадр 16:9 внутри
ART = {
    "kumoi": dict(commons="File:Hiroshi Yoshida - Kumoi-Zakura (Kumoi Cherry Trees) - Google Art Project.jpg",
                  artist="Хироси Ёсида", title="Кумои-дзакура", date="1926",
                  crop=(0.025, 0.02, 0.975, 0.93), bg=(0.0, 0.0, 1.0, 0.7)),
    "yasumasa": dict(aic=102619, artist="Цукиока Ёситоси", title="Фудзивара-но Ясумаса играет на флейте при луне",
                     date="около 1883", crop=(0.0, 0.0, 1.0, 1.0), bg=(0.0, 0.0, 0.94, 1.0)),
    "mitsuoki": dict(aic=127643, artist="Тоса Мицуоки", title="Цветущая сакура и осенние клёны с листками стихов",
                     date="1654–1681", crop=(0.0, 0.0, 1.0, 1.0), bg=(0.06, 0.0, 0.94, 1.0)),
    "utamaro": dict(aic=110739, artist="Китагава Утамаро", title="Пир под цветущей сакурой",
                    date="конец XVIII века", crop=(0.01, 0.015, 0.99, 0.985), bg=(0.03, 0.0, 0.97, 1.0)),
    "moon-smoke": dict(aic=197414, artist="Цукиока Ёситоси", title="Луна и дым. Из серии «Сто видов луны»",
                       date="1886", crop=(0.0, 0.0, 1.0, 1.0), bg=(0.0, 0.03, 1.0, 0.45)),
    "yozakura": dict(aic=25445, artist="Утагава Хиросигэ", title="Ночная сакура на Накано-тё в Ёсиваре",
                     date="около 1832–1838", crop=(0.0, 0.0, 0.93, 1.0), bg=(0.0, 0.0, 0.93, 0.9)),
    "kanbara": dict(aic=25613, artist="Утагава Хиросигэ", title="Канбара: вечерний снег",
                    date="около 1833–1834", crop=(0.02, 0.03, 0.98, 0.97), bg=(0.02, 0.03, 0.98, 0.97)),
    "hirosaki": dict(commons="File:Hirosaki Castle.JPG", artist="Фото Kojin", title="Замок Хиросаки и ночная сакура",
                     date="2010", crop=(0.0, 0.0, 1.0, 1.0), bg=(0.0, 0.0, 1.0, 1.0)),
    "yuzu-scroll": dict(aic=56731, artist="Неизвестный мастер", title="Легенды секты Юдзу Нэмбуцу (свиток эмакимоно)",
                        date="XIV век", crop=(0.0, 0.0, 1.0, 1.0)),
    "crow": dict(aic=28223, artist="Каванабэ Кёсай", title="Ворон на сосновой ветке", date="1868–1889",
                 crop=(0.0, 0.0, 1.0, 1.0)),
}


def _get(url: str, raw: bool = False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read() if raw else json.load(r)


def download(key: str, spec: dict) -> Path:
    dst = RAW / key
    img_path, meta_path = dst / "original.jpg", dst / "meta.json"
    if img_path.exists() and meta_path.exists():
        return img_path
    dst.mkdir(parents=True, exist_ok=True)
    if "aic" in spec:
        d = _get(f"https://api.artic.edu/api/v1/artworks/{spec['aic']}"
                 "?fields=id,title,artist_title,date_display,image_id,is_public_domain,credit_line")["data"]
        if not d.get("is_public_domain"):
            raise SystemExit(f"{key}: AIC не отмечает работу как public domain — не берём")
        url = f"https://www.artic.edu/iiif/2/{d['image_id']}/full/3000,/0/default.jpg"
        meta = {"source": "Art Institute of Chicago", "license": "Public domain (CC0)",
                "page": f"https://www.artic.edu/artworks/{spec['aic']}", **d}
    else:
        q = _get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "format": "json", "titles": spec["commons"], "prop": "imageinfo",
            "iiprop": "url|extmetadata", "iiurlwidth": 3000}))
        ii = next(iter(q["query"]["pages"].values()))["imageinfo"][0]
        lic = ii["extmetadata"].get("LicenseShortName", {}).get("value", "")
        if not any(s in lic.lower() for s in ("public domain", "cc0")):
            raise SystemExit(f"{key}: лицензия «{lic}» — не public domain, не берём")
        url = ii.get("thumburl") or ii["url"]
        meta = {"source": "Wikimedia Commons", "license": lic, "page": ii["descriptionurl"], "title": spec["commons"]}
    img_path.write_bytes(_get(url, raw=True))
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  [скачано] {key}: {img_path.stat().st_size / 1e6:.1f} МБ — {meta['page']}")
    return img_path


def download_fonts():
    for name, path in (("yujisyuku", "YujiSyuku-Regular.ttf"), ("yujisyuku", "OFL.txt")):
        dst = FONTS / name / path
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(_get(f"https://raw.githubusercontent.com/google/fonts/main/ofl/{name}/{path}", raw=True))
            print(f"  [скачано] шрифт {name}/{path}")


def main():
    offline = "--offline" in sys.argv
    if not offline:
        download_fonts()
        for key, spec in ART.items():
            download(key, spec)
    import art_process  # обработка — в отдельном модуле, чтобы её можно было крутить без сети
    art_process.process_all(ART, RAW, VIDEO_SRC, ART_DIR)


if __name__ == "__main__":
    main()
