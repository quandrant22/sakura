// Картинка персонажа. Если владелец положит src/assets/character.png — показываем её,
// иначе заглушка: розово-фиолетовый градиент и силуэт.
const assets = import.meta.glob<string>("../assets/character.png", { eager: true, import: "default" });
const characterUrl: string | undefined = Object.values(assets)[0];

export function CharacterArt({ className = "", fade = true }: { className?: string; fade?: boolean }) {
  return (
    <div className={"relative overflow-hidden " + className}>
      {characterUrl ? (
        <img src={characterUrl} alt="Sakura" className="h-full w-full object-cover" />
      ) : (
        <div className="h-full w-full bg-gradient-to-br from-[#ff7eb9] via-[#b06ad8] to-[#3b2063]" aria-label="Sakura">
          <svg viewBox="0 0 200 240" className="absolute inset-x-0 bottom-0 mx-auto h-[88%] opacity-70" aria-hidden="true">
            <defs>
              <linearGradient id="sil" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#2a1240" stopOpacity="0.55" />
                <stop offset="1" stopColor="#12081d" stopOpacity="0.95" />
              </linearGradient>
            </defs>
            {/* волосы, голова, плечи */}
            <path d="M58 92c0-34 19-58 42-58s42 24 42 58c0 18-4 40-10 56H68c-6-16-10-38-10-56Z" fill="url(#sil)" />
            <ellipse cx="100" cy="92" rx="30" ry="36" fill="url(#sil)" />
            <path d="M30 240c4-46 32-74 70-74s66 28 70 74Z" fill="url(#sil)" />
            <circle cx="132" cy="58" r="9" fill="#ff4d94" opacity="0.8" />
          </svg>
        </div>
      )}
      {fade && <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-panel" />}
    </div>
  );
}
