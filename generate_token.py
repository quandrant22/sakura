"""
generate_token.py — генерирует WS_SECRET для .env

Запусти один раз:
    python generate_token.py

Скопируй вывод в .env на VPS (WS_SECRET=...)
и в .env на агенте (WS_TOKEN=...).
Оба значения должны совпадать.
"""
import secrets

token = secrets.token_hex(32)
print(f"WS_SECRET={token}")
print()
print("Скопируй это значение в:")
print(f"  VPS:   .env  →  WS_SECRET={token}")
print(f"  Агент: .env  →  WS_TOKEN={token}")
