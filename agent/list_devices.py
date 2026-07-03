"""
list_devices.py — утилита для диагностики аудио-устройств.

Запусти перед настройкой Сакуры чтобы узнать номер нужного устройства:
    python list_devices.py

Вывод покажет все доступные устройства. Скопируй нужный номер
в .env: AUDIO_OUTPUT_DEVICE=2 (или имя: AUDIO_OUTPUT_DEVICE=Realtek)
"""

import sys

def main():
    try:
        import sounddevice as sd
    except ImportError:
        print("sounddevice не установлен: pip install sounddevice")
        return

    print("=" * 60)
    print("  Аудио-устройства вывода (для AUDIO_OUTPUT_DEVICE в .env)")
    print("=" * 60)

    try:
        devices   = sd.query_devices()
        default_o = sd.default.device[1]   # индекс дефолтного output
    except Exception as e:
        print(f"Ошибка: {e}")
        return

    output_found = False
    for i, dev in enumerate(devices):
        if dev["max_output_channels"] <= 0:
            continue
        output_found = True
        marker = " ◀ ДЕФОЛТ (Windows)" if i == default_o else ""
        print(f"  [{i:2d}]  {dev['name']}{marker}")
        print(f"        каналов: {dev['max_output_channels']}, "
              f"частота: {int(dev['default_samplerate'])} Гц")

    if not output_found:
        print("  Нет устройств вывода!")
        return

    print()
    print("=" * 60)
    print("  Настройка в .env:")
    print()
    print("  # Устройство по умолчанию Windows (рекомендуется):")
    print("  AUDIO_OUTPUT_DEVICE=default")
    print()
    print("  # Конкретное устройство по номеру:")
    print(f"  AUDIO_OUTPUT_DEVICE={default_o}  # (дефолт)")
    print()
    print("  # Поиск по имени (частичное совпадение):")
    try:
        default_dev = devices[default_o]
        name_hint = default_dev["name"].split("(")[0].strip()
        print(f"  AUDIO_OUTPUT_DEVICE={name_hint}")
    except Exception:
        pass
    print("=" * 60)

    # Дополнительно: тест воспроизведения
    print()
    answer = input("Воспроизвести тестовый сигнал на устройстве по умолчанию? [y/N] ").strip().lower()
    if answer == "y":
        try:
            import numpy as np
            duration = 0.3
            rate     = 24000
            t        = np.linspace(0, duration, int(rate * duration))
            tone     = (np.sin(2 * np.pi * 880 * t) * 0.3 * 32767).astype(np.int16)
            sd.play(tone, samplerate=rate, device=default_o)
            sd.wait()
            print("✓ Звук воспроизведён. Если не слышно — попробуй другое устройство.")
        except Exception as e:
            print(f"Ошибка воспроизведения: {e}")


if __name__ == "__main__":
    main()
