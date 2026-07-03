"""
Запусти на VPS чтобы проверить что реально загружается из Steam API.
python steam_check.py
"""
import urllib.request, json, sys

# Вставь свои данные из config.py
STEAM_KEY = input("Steam API key: ").strip()
STEAM_ID  = input("Steam ID: ").strip()

url = (
    f"http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
    f"?key={STEAM_KEY}&steamid={STEAM_ID}&include_appinfo=true"
    f"&include_played_free_games=true&format=json"
)

with urllib.request.urlopen(url, timeout=10) as r:
    data = json.loads(r.read())

games = data.get("response", {}).get("games", [])
print(f"\nВсего игр: {len(games)}")

played = [g for g in games if g.get("playtime_forever", 0) > 0]
unplayed = [g for g in games if g.get("playtime_forever", 0) == 0]
print(f"С временем (>0 мин): {len(played)}")
print(f"Не запускались: {len(unplayed)}")

print(f"\nТоп-20 по времени:")
for g in sorted(played, key=lambda x: x.get("playtime_forever", 0), reverse=True)[:20]:
    h = g["playtime_forever"] // 60
    m = g["playtime_forever"] % 60
    print(f"  {h}ч {m}м  —  {g['name']}")

print(f"\nПервые 5 в несортированном списке (то что видит Сакура если сортировка сломана):")
for g in games[:5]:
    print(f"  {g.get('name')} ({g.get('playtime_forever',0)} мин)")
