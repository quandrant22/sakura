"""
Generates clean, scalable SVG vector diagrams for the website.
"""

import os

OUT_DIAGRAMS = "site/media/images/diagrams"

def make_voice_pipeline_svg():
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 700" width="100%" height="100%" style="background:#0D091A; font-family:'Segoe UI', sans-serif;">
  <defs>
    <linearGradient id="gradPink" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FF6AE3"/>
      <stop offset="100%" stop-color="#B829A0"/>
    </linearGradient>
    <linearGradient id="gradCyan" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#4FD8FF"/>
      <stop offset="100%" stop-color="#1B75BB"/>
    </linearGradient>
    <linearGradient id="gradGreen" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#10B981"/>
      <stop offset="100%" stop-color="#047857"/>
    </linearGradient>
    <linearGradient id="gradAmber" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FFCF6B"/>
      <stop offset="100%" stop-color="#D97706"/>
    </linearGradient>
    <filter id="glowPink" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="8" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over"/>
    </filter>
  </defs>

  <!-- Header -->
  <text x="50" y="55" fill="#FFFFFF" font-size="28" font-weight="bold">ГОЛОСОВОЙ КОНВЕЙЕР SAKURA AI (GigaAM v2_ctc + Fast-Path + Live TTS)</text>
  <text x="50" y="85" fill="#FF6AE3" font-size="16">Полная сквозная задержка (Time to First Audio Chunk) сокращена с 1800 мс до 320–480 мс</text>

  <!-- Stage 1 -->
  <g transform="translate(50, 130)">
    <rect width="330" height="480" rx="16" fill="#150F26" stroke="#4FD8FF" stroke-width="2"/>
    <rect width="330" height="45" rx="16" fill="#1C1433"/>
    <text x="20" y="30" fill="#4FD8FF" font-size="18" font-weight="bold">1. ЗАХВАТ И STT</text>
    
    <!-- Item 1 -->
    <rect x="20" y="70" width="290" height="110" rx="12" fill="#20173D" stroke="#4FD8FF" stroke-opacity="0.4"/>
    <text x="35" y="100" fill="#4FD8FF" font-size="16" font-weight="bold">WASAPI Audio Ingest</text>
    <text x="35" y="125" fill="#D1D5DB" font-size="13">Захват микрофона + loopback</text>
    <text x="35" y="145" fill="#9CA3AF" font-size="12">Resampling 48kHz -> 16kHz</text>
    <text x="35" y="165" fill="#10B981" font-size="12">PortAudio drain (0 задержки)</text>

    <!-- Item 2 -->
    <rect x="20" y="200" width="290" height="110" rx="12" fill="#20173D" stroke="#4FD8FF" stroke-opacity="0.4"/>
    <text x="35" y="230" fill="#FFCF6B" font-size="16" font-weight="bold">Silero VAD v6.2</text>
    <text x="35" y="255" fill="#D1D5DB" font-size="13">Детекция речи в потоке</text>
    <text x="35" y="275" fill="#9CA3AF" font-size="12">Адаптивный порог RMS dB</text>
    <text x="35" y="295" fill="#10B981" font-size="12">Отсечка тишины за 40 мс</text>

    <!-- Item 3 -->
    <rect x="20" y="330" width="290" height="120" rx="12" fill="#20173D" stroke="#FF6AE3" stroke-opacity="0.6"/>
    <text x="35" y="360" fill="#FF6AE3" font-size="16" font-weight="bold">GigaAM v2_ctc</text>
    <text x="35" y="385" fill="#D1D5DB" font-size="13">Русская нейро-ASR модель</text>
    <text x="35" y="405" fill="#9CA3AF" font-size="12">Снятие перегрузок клиппинга</text>
    <text x="35" y="425" fill="#10B981" font-size="12">Нормализация имён и числительных</text>
  </g>

  <!-- Arrow 1 -> 2 -->
  <path d="M 400 370 L 440 370" stroke="#FF6AE3" stroke-width="4" stroke-dasharray="6,4"/>
  <polygon points="440,364 452,370 440,376" fill="#FF6AE3"/>

  <!-- Stage 2 -->
  <g transform="translate(460, 130)">
    <rect width="330" height="480" rx="16" fill="#150F26" stroke="#10B981" stroke-width="2"/>
    <rect width="330" height="45" rx="16" fill="#1C1433"/>
    <text x="20" y="30" fill="#10B981" font-size="18" font-weight="bold">2. NLU И РОУТЕР</text>

    <!-- Item 1 -->
    <rect x="20" y="70" width="290" height="110" rx="12" fill="#20173D" stroke="#10B981" stroke-opacity="0.4"/>
    <text x="35" y="100" fill="#EF4444" font-size="16" font-weight="bold">Early Gate (Barge-in)</text>
    <text x="35" y="125" fill="#D1D5DB" font-size="13">Мгновенный перехват «стоп»</text>
    <text x="35" y="145" fill="#9CA3AF" font-size="12">Сброс TTS очереди на лету</text>
    <text x="35" y="165" fill="#10B981" font-size="12">Прерывание речи за 15 мс</text>

    <!-- Item 2 -->
    <rect x="20" y="200" width="290" height="110" rx="12" fill="#20173D" stroke="#10B981" stroke-opacity="0.8"/>
    <text x="35" y="230" fill="#10B981" font-size="16" font-weight="bold">v3 Fast-Path Router</text>
    <text x="35" y="255" fill="#D1D5DB" font-size="13">140 возможностей реестра</text>
    <text x="35" y="275" fill="#9CA3AF" font-size="12">Regex + нормализация форм</text>
    <text x="35" y="295" fill="#10B981" font-size="12">Исполнение за 1.8 мс без LLM!</text>

    <!-- Item 3 -->
    <rect x="20" y="330" width="290" height="120" rx="12" fill="#20173D" stroke="#FFCF6B" stroke-opacity="0.4"/>
    <text x="35" y="360" fill="#FFCF6B" font-size="16" font-weight="bold">State Arbiter</text>
    <text x="35" y="385" fill="#D1D5DB" font-size="13">Единый блок «СОСТОЯНИЕ»</text>
    <text x="35" y="405" fill="#9CA3AF" font-size="12">Игры, окна, медиа, статус ПК</text>
    <text x="35" y="425" fill="#10B981" font-size="12">Zero-Hallucination фильтр</text>
  </g>

  <!-- Arrow 2 -> 3 -->
  <path d="M 810 370 L 850 370" stroke="#FF6AE3" stroke-width="4" stroke-dasharray="6,4"/>
  <polygon points="850,364 862,370 850,376" fill="#FF6AE3"/>

  <!-- Stage 3 -->
  <g transform="translate(870, 130)">
    <rect width="330" height="480" rx="16" fill="#150F26" stroke="#FF6AE3" stroke-width="2"/>
    <rect width="330" height="45" rx="16" fill="#1C1433"/>
    <text x="20" y="30" fill="#FF6AE3" font-size="18" font-weight="bold">3. НЕЙРОСЕТЕВОЙ МОЗГ</text>

    <!-- Item 1 -->
    <rect x="20" y="70" width="290" height="110" rx="12" fill="#20173D" stroke="#FF6AE3" stroke-opacity="0.4"/>
    <text x="35" y="100" fill="#4FD8FF" font-size="16" font-weight="bold">LLM Classifier Fallback</text>
    <text x="35" y="125" fill="#D1D5DB" font-size="13">Для нестандартных фраз</text>
    <text x="35" y="145" fill="#9CA3AF" font-size="12">Пул fallback-моделей</text>
    <text x="35" y="165" fill="#10B981" font-size="12">Переключение за 250 мс</text>

    <!-- Item 2 -->
    <rect x="20" y="200" width="290" height="110" rx="12" fill="#20173D" stroke="#FF6AE3" stroke-opacity="0.8"/>
    <text x="35" y="230" fill="#FF6AE3" font-size="16" font-weight="bold">Gemini Live / Gemma 4</text>
    <text x="35" y="255" fill="#D1D5DB" font-size="13">Стриминг токенов по WS</text>
    <text x="35" y="275" fill="#9CA3AF" font-size="12">Token-bucket rate limiter</text>
    <text x="35" y="295" fill="#10B981" font-size="12">Лимиты RPM / RPD в безопасности</text>

    <!-- Item 3 -->
    <rect x="20" y="330" width="290" height="120" rx="12" fill="#20173D" stroke="#FFCF6B" stroke-opacity="0.4"/>
    <text x="35" y="360" fill="#FFCF6B" font-size="16" font-weight="bold">Emotional Core [ТОН:]</text>
    <text x="35" y="385" fill="#D1D5DB" font-size="13">Интонации: сарказм, нежность</text>
    <text x="35" y="405" fill="#9CA3AF" font-size="12">Ремарки вырезаются из звука</text>
    <text x="35" y="425" fill="#10B981" font-size="12">Изоляция интим-режима</text>
  </g>

  <!-- Arrow 3 -> 4 -->
  <path d="M 1220 370 L 1260 370" stroke="#FF6AE3" stroke-width="4" stroke-dasharray="6,4"/>
  <polygon points="1260,364 1272,370 1260,376" fill="#FF6AE3"/>

  <!-- Stage 4 -->
  <g transform="translate(1280, 130)">
    <rect width="280" height="480" rx="16" fill="#150F26" stroke="#4FD8FF" stroke-width="2"/>
    <rect width="280" height="45" rx="16" fill="#1C1433"/>
    <text x="20" y="30" fill="#4FD8FF" font-size="18" font-weight="bold">4. TTS СИНТЕЗ</text>

    <!-- Item 1 -->
    <rect x="20" y="70" width="240" height="110" rx="12" fill="#20173D" stroke="#4FD8FF" stroke-opacity="0.4"/>
    <text x="35" y="100" fill="#10B981" font-size="16" font-weight="bold">Live TTS Session</text>
    <text x="35" y="125" fill="#D1D5DB" font-size="13">Producer-consumer конвейер</text>
    <text x="35" y="145" fill="#9CA3AF" font-size="12">Единая сессия на ответ</text>
    <text x="35" y="165" fill="#10B981" font-size="12">Мелкие чанки (80 симв)</text>

    <!-- Item 2 -->
    <rect x="20" y="200" width="240" height="110" rx="12" fill="#20173D" stroke="#4FD8FF" stroke-opacity="0.4"/>
    <text x="35" y="230" fill="#FF6AE3" font-size="16" font-weight="bold">asyncio.Queue</text>
    <text x="35" y="255" fill="#D1D5DB" font-size="13">Потоковое воспроизведение</text>
    <text x="35" y="275" fill="#9CA3AF" font-size="12">Защита от underrun</text>
    <text x="35" y="295" fill="#10B981" font-size="12">Плавная бесшовная склейка</text>

    <!-- Item 3 -->
    <rect x="20" y="330" width="240" height="120" rx="12" fill="#20173D" stroke="#4FD8FF" stroke-opacity="0.4"/>
    <text x="35" y="360" fill="#4FD8FF" font-size="16" font-weight="bold">Вывод звука & HUD</text>
    <text x="35" y="385" fill="#D1D5DB" font-size="13">Динамики / VB-CABLE</text>
    <text x="35" y="405" fill="#9CA3AF" font-size="12">Анимация капли Сакуры</text>
    <text x="35" y="425" fill="#10B981" font-size="12">Катакана «発話中»</text>
  </g>

  <!-- Bottom status bar -->
  <rect x="50" y="635" width="1510" height="45" rx="10" fill="#1C1433" stroke="#FF6AE3" stroke-opacity="0.3"/>
  <text x="75" y="663" fill="#FFFFFF" font-size="14" font-weight="bold">SAKURA PIPELINE: 100% асинхронный цикл на asyncio, нулевая блокировка интерфейса, мгновенный отклик на прерывание «стоп».</text>
</svg>'''
    with open(os.path.join(OUT_DIAGRAMS, "voice-pipeline.svg"), "w", encoding="utf-8") as f:
        f.write(svg)
    print("Saved voice-pipeline.svg")

def make_noise_handshake_svg():
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 750" width="100%" height="100%" style="background:#0D091A; font-family:'Segoe UI', sans-serif;">
  <defs>
    <linearGradient id="nPink" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FF6AE3"/>
      <stop offset="100%" stop-color="#B829A0"/>
    </linearGradient>
    <linearGradient id="nCyan" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#4FD8FF"/>
      <stop offset="100%" stop-color="#1B75BB"/>
    </linearGradient>
  </defs>

  <text x="50" y="55" fill="#FFFFFF" font-size="28" font-weight="bold">ПРОТОКОЛ БЕЗОПАСНОСТИ: Noise_IK_25519_ChaChaPoly_BLAKE2s</text>
  <text x="50" y="85" fill="#4FD8FF" font-size="16">Формально верифицированный сквозной криптоканал между Desktop-клиентом и сервером (ProVerif ik.pv &amp; xxpsk3.pv)</text>

  <!-- Client Box -->
  <rect x="50" y="120" width="380" height="580" rx="16" fill="#150F26" stroke="#FF6AE3" stroke-width="2"/>
  <rect x="50" y="120" width="380" height="50" rx="16" fill="#20173D"/>
  <text x="70" y="152" fill="#FF6AE3" font-size="18" font-weight="bold">DESKTOP CLIENT (ПК Мастера)</text>
  <text x="70" y="200" fill="#FFCF6B" font-size="15" font-weight="bold">Статический ключ s_client (X25519):</text>
  <text x="70" y="225" fill="#D1D5DB" font-size="13">Хранится в Windows DPAPI шифровании</text>
  <text x="70" y="245" fill="#9CA3AF" font-size="12">Никогда не передаётся в открытом виде</text>

  <text x="70" y="295" fill="#4FD8FF" font-size="15" font-weight="bold">Эфемерный ключ e_client:</text>
  <text x="70" y="320" fill="#D1D5DB" font-size="13">Генерируется заново на каждую сессию</text>
  <text x="70" y="340" fill="#10B981" font-size="12">Обеспечивает Perfect Forward Secrecy</text>

  <rect x="70" y="380" width="340" height="150" rx="12" fill="#1A1230" stroke="#FF6AE3" stroke-opacity="0.4"/>
  <text x="85" y="410" fill="#FF6AE3" font-size="15" font-weight="bold">Защитные барьеры:</text>
  <text x="85" y="435" fill="#D1D5DB" font-size="13">• Запрет отката на bearer-токены (4412)</text>
  <text x="85" y="460" fill="#D1D5DB" font-size="13">• Окно защиты от повторов (Anti-Replay 64)</text>
  <text x="85" y="485" fill="#D1D5DB" font-size="13">• Контроль порядка и целостности кадров</text>
  <text x="85" y="510" fill="#10B981" font-size="13">• Логи очищены от секретов и ключей</text>

  <!-- Server Box -->
  <rect x="1170" y="120" width="380" height="580" rx="16" fill="#150F26" stroke="#4FD8FF" stroke-width="2"/>
  <rect x="1170" y="120" width="380" height="50" rx="16" fill="#20173D"/>
  <text x="1190" y="152" fill="#4FD8FF" font-size="18" font-weight="bold">VPS CORE SERVER (Облако)</text>
  <text x="1190" y="200" fill="#FFCF6B" font-size="15" font-weight="bold">Статический ключ s_server (X25519):</text>
  <text x="1190" y="225" fill="#D1D5DB" font-size="13">Публичный ключ встроен в клиент</text>
  <text x="1190" y="245" fill="#9CA3AF" font-size="12">Приватный ключ изолирован в root</text>

  <text x="1190" y="295" fill="#4FD8FF" font-size="15" font-weight="bold">Реестр доверенных устройств:</text>
  <text x="1190" y="320" fill="#D1D5DB" font-size="13">Белый список SHA-256 отпечатков</text>
  <text x="1190" y="340" fill="#10B981" font-size="12">Мгновенный отзыв через /revoke</text>

  <rect x="1190" y="380" width="340" height="150" rx="12" fill="#1A1230" stroke="#4FD8FF" stroke-opacity="0.4"/>
  <text x="1205" y="410" fill="#4FD8FF" font-size="15" font-weight="bold">Механизмы ядра:</text>
  <text x="1205" y="435" fill="#D1D5DB" font-size="13">• 0-RTT аутентификация по известному ключу</text>
  <text x="1205" y="460" fill="#D1D5DB" font-size="13">• Автоматический Rekey после 10k кадров</text>
  <text x="1205" y="485" fill="#D1D5DB" font-size="13">• Фрагментация сообщений до 2 МиБ</text>
  <text x="1205" y="510" fill="#10B981" font-size="13">• Защита от зондирования чужих ключей</text>

  <!-- Flow Center -->
  <rect x="460" y="120" width="680" height="430" rx="16" fill="#120D22" stroke="#604585" stroke-width="1"/>
  <text x="490" y="160" fill="#FFFFFF" font-size="18" font-weight="bold">1-RTT РУКОПОЖАТИЕ NOISE IK</text>

  <!-- Step 1 Arrow -->
  <g transform="translate(480, 190)">
    <rect width="640" height="100" rx="10" fill="#1B1333" stroke="#FF6AE3" stroke-opacity="0.7"/>
    <text x="20" y="30" fill="#FF6AE3" font-size="15" font-weight="bold">1. Инициализация (Client -> Server): -> e, es, s, ss</text>
    <text x="20" y="55" fill="#D1D5DB" font-size="13">• DH(e, s_server) шифрует статический ключ клиента s_client</text>
    <text x="20" y="75" fill="#D1D5DB" font-size="13">• DH(s_client, s_server) обеспечивает аутентификацию отправителя</text>
    <path d="M 580 50 L 620 50" stroke="#FF6AE3" stroke-width="3"/>
    <polygon points="620,45 630,50 620,55" fill="#FF6AE3"/>
  </g>

  <!-- Step 2 Arrow -->
  <g transform="translate(480, 310)">
    <rect width="640" height="100" rx="10" fill="#1B1333" stroke="#4FD8FF" stroke-opacity="0.7"/>
    <text x="20" y="30" fill="#4FD8FF" font-size="15" font-weight="bold">2. Ответ (Server -> Client): <- e, ee, se</text>
    <text x="20" y="55" fill="#D1D5DB" font-size="13">• DH(e_server, e_client) + DH(s_client, e_server)</text>
    <text x="20" y="75" fill="#D1D5DB" font-size="13">• Вывод двух симметричных ключей: k_client_to_server, k_server_to_client</text>
    <path d="M 60 50 L 20 50" stroke="#4FD8FF" stroke-width="3"/>
    <polygon points="20,45 10,50 20,55" fill="#4FD8FF"/>
  </g>

  <!-- Step 3 Transport -->
  <g transform="translate(480, 430)">
    <rect width="640" height="100" rx="10" fill="#1B1333" stroke="#10B981" stroke-opacity="0.8"/>
    <text x="20" y="30" fill="#10B981" font-size="15" font-weight="bold">3. Транспортные кадры «SK» (ChaCha20-Poly1305 + BLAKE2s)</text>
    <text x="20" y="55" fill="#D1D5DB" font-size="13">• Полнодуплексный шифрованный канал команд и звука</text>
    <text x="20" y="75" fill="#10B981" font-size="13">• Полная невозможность подделки и перехвата даже при взломе TLS</text>
  </g>

  <!-- Formal Verification Card -->
  <rect x="460" y="570" width="680" height="130" rx="16" fill="#0A2818" stroke="#10B981" stroke-width="2"/>
  <text x="490" y="605" fill="#FFCF6B" font-size="16" font-weight="bold">РЕЗУЛЬТАТЫ ФОРМАЛЬНОГО ДОКАЗАТЕЛЬСТВА В PROVERIF:</text>
  <text x="490" y="635" fill="#10B981" font-size="14" font-weight="bold">RESULT not attacker(secret_client[]) is TRUE (Тайна сессии клиента доказана)</text>
  <text x="490" y="660" fill="#10B981" font-size="14" font-weight="bold">RESULT not attacker(secret_server[]) is TRUE (Тайна сессии сервера доказана)</text>
  <text x="490" y="685" fill="#10B981" font-size="14" font-weight="bold">RESULT inj-event(ServerAuth) ==> inj-event(ClientInit) is TRUE (Аутентичность)</text>
</svg>'''
    with open(os.path.join(OUT_DIAGRAMS, "noise-handshake.svg"), "w", encoding="utf-8") as f:
        f.write(svg)
    print("Saved noise-handshake.svg")

if __name__ == "__main__":
    make_voice_pipeline_svg()
    make_noise_handshake_svg()
