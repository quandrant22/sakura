// Настройки → «Подключение»: мастер первого запуска по шагам — устройство и сервер, защищённый канал,
// микрофон и колонки, слово «Сакура», расширение браузера, токен Яндекс.Музыки, итоговая проверка.
import { CheckCircle2, ChevronLeft, ChevronRight, Circle, Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useMediaClient } from "../media/MediaContext";
import { errorText, useApp } from "../store";

const input = "rounded-lg border border-line bg-panel2 px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent";
const btn = "flex items-center gap-1 rounded-full border border-line px-3 py-1 text-xs text-ink-dim hover:text-ink disabled:opacity-40";

export const STEPS = ["Устройство и сервер", "Защищённый канал", "Микрофон и колонки", "Слово «Сакура»",
                      "Расширение браузера", "Яндекс.Музыка", "Проверка"] as const;

interface Cfg { values: Record<string, string>; running: Record<string, string> }
export interface Problem { text: string; step: number }

/** Итоговая проверка: что не так и на какой шаг вести «Исправить». */
export function findProblems(p: { server: boolean; mic: boolean; wakeOk: boolean | null; ext: boolean; ymToken: boolean;
                                   secure: boolean }): Problem[] {
  const out: Problem[] = [];
  if (!p.server) out.push({ text: "Нет связи с сервером — проверьте адрес и токен", step: 0 });
  if (!p.secure) out.push({ text: "Канал не защищён — подключите устройство или включите VPN", step: 1 });
  if (!p.mic) out.push({ text: "Микрофон выключен", step: 2 });
  if (p.wakeOk === false) out.push({ text: "Слово «Сакура» не распозналось — проверьте микрофон и чувствительность", step: 3 });
  if (!p.ext) out.push({ text: "Расширение браузера не подключено", step: 4 });
  if (!p.ymToken) out.push({ text: "Нет токена Яндекс.Музыки — лайки и текст песен недоступны", step: 5 });
  return out;
}

export function ConnectionWizard() {
  const client = useMediaClient();
  const settings = useApp((s) => s.settings);
  const server = useApp((s) => s.server);
  const coreState = useApp((s) => s.coreState);
  const toggleMic = useApp((s) => s.toggleMic);
  const [step, setStep] = useState(0);
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const [level, setLevel] = useState<number | null>(null);
  const [wake, setWake] = useState<"idle" | "waiting" | "ok" | "fail">("idle");
  const [ymSet, setYmSet] = useState<boolean | null>(null);
  const tokenRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let alive = true;
    client.call<Cfg>("config_values").then((r) => { if (alive) { setCfg(r); setForm(r.values); } }, () => {});
    client.call<{ keys: Record<string, boolean> }>("secrets_status").then(
      (r) => { if (alive) setYmSet(Boolean(r.keys.YANDEX_MUSIC_TOKEN)); }, () => {});
    return () => { alive = false; };
  }, [client]);

  // живой индикатор фона микрофона на шаге «Микрофон и колонки»
  useEffect(() => {
    if (step !== 2) return;
    const t = setInterval(() => {
      client.call<{ db: number | null }>("mic_level").then((r) => setLevel(r.db), () => setLevel(null));
    }, 500);
    return () => clearInterval(t);
  }, [client, step]);

  // «Скажите «Сакура»»: успех — слух перешёл в «слушаю» за 15 с
  if (wake === "waiting" && coreState === "listening") setWake("ok");
  useEffect(() => {
    if (wake !== "waiting") return;
    const t = setTimeout(() => setWake("fail"), 15000);
    return () => clearTimeout(t);
  }, [wake, coreState]);

  const save = async (key: string) => {
    try { await client.call("config_set", { key, value: form[key] ?? "" }); setMsg("Сохранено. Перезапустите ядро, чтобы применить."); }
    catch (e) { setMsg(errorText(e)); }
  };
  const saveToken = async () => {
    const el = tokenRef.current;
    const value = el?.value ?? "";
    if (el) el.value = "";
    if (!value.trim()) return;
    try { await client.call("secrets_set", { key: "YANDEX_MUSIC_TOKEN", value }); setYmSet(true); setMsg("Токен сохранён"); }
    catch (e) { setMsg(errorText(e)); }
  };
  const sound = async () => {
    try { await client.call("sound_test"); setMsg("Слышите короткий звук? Если нет — выберите другое устройство в Настройки → Звук"); }
    catch (e) { setMsg(errorText(e)); }
  };

  const secure = settings?.server_transport === "noise" || settings?.server_transport === "noise-only"
    || String(settings?.server_url ?? "").startsWith("wss://");
  const problems = findProblems({ server: server.online, mic: Boolean(settings?.mic_enabled ?? true),
    wakeOk: wake === "ok" ? true : wake === "fail" ? false : null, ext: Boolean(settings?.extension_connected),
    ymToken: Boolean(ymSet), secure });

  const field = (key: string, label: string, hint: string) => (
    <label className="grid grid-cols-[minmax(0,160px)_minmax(0,1fr)_auto] items-center gap-3 py-2">
      <span className="min-w-0"><span className="block text-sm text-ink">{label}</span><span className="text-xs text-ink-dim">{hint}</span></span>
      <input aria-label={label} value={form[key] ?? ""} onChange={(e) => setForm({ ...form, [key]: e.target.value })}
             className={input + " min-w-0 w-full"} />
      <button type="button" className={btn} onClick={() => void save(key)}>Сохранить</button>
    </label>
  );

  return (
    <div className="px-4 pb-3 text-sm">
      <ol aria-label="Шаги мастера" className="mb-3 flex flex-wrap gap-2 text-xs">
        {STEPS.map((s, i) => (
          <li key={s}>
            <button type="button" onClick={() => setStep(i)} aria-current={i === step ? "step" : undefined}
                    className={"rounded-full px-2.5 py-1 " + (i === step ? "bg-accent/20 text-ink" : "text-ink-dim hover:text-ink")}>
              {i + 1}. {s}
            </button>
          </li>
        ))}
      </ol>
      <section aria-label={STEPS[step]} className="min-h-[150px] rounded-btn bg-panel2/50 p-3">
        {step === 0 && (
          <>
            {field("DEVICE_ID", "Имя устройства", "Латиница: mostech, laptop")}
            {field("VPS_WS_URL", "Адрес сервера", "ws://адрес:8765")}
            {field("SERVER_TRANSPORT", "Режим канала", "ws, noise (защищённый с откатом), noise-only")}
            <div className="text-xs text-ink-dim">Сейчас работает: {cfg?.running.DEVICE_ID} · {cfg?.running.VPS_WS_URL} · {cfg?.running.SERVER_TRANSPORT}
              {" · сервер "}<span className={server.online ? "text-online" : "text-warn"}>{server.online ? "на связи" : "нет связи"}</span></div>
            <div className="mt-1 text-xs text-ink-dim">Токен сервера — в разделе «Секреты».</div>
          </>
        )}
        {step === 1 && (
          <div className="space-y-1 text-xs text-ink">
            <div>Канал сейчас: <span className={secure ? "text-online" : "text-warn"}>{secure ? "защищён" : "не защищён"}</span></div>
            <div className="text-ink-dim">Подключите устройство в Настройки → «Безопасность»: в Telegram отправьте /pair и введите 8 слов
              или загрузите QR. Затем выберите режим канала noise на шаге 1. Если пользуетесь VPN до сервера — этот шаг можно пропустить.</div>
          </div>
        )}
        {step === 2 && (
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="w-24 text-xs text-ink-dim">Микрофон</span>
              <div aria-label="Уровень микрофона" className="h-2 w-48 overflow-hidden rounded-full bg-panel">
                <div className="h-full bg-accent" style={{ width: `${level == null ? 0 : Math.max(0, Math.min(100, (level + 70) * 1.6))}%` }} />
              </div>
              <span className="text-xs text-ink-dim">{level == null ? "нет данных" : `${level} dB`}</span>
              {!(settings?.mic_enabled ?? true) && <button type="button" className={btn} onClick={() => void toggleMic()}>Включить микрофон</button>}
            </div>
            <div className="flex items-center gap-3">
              <span className="w-24 text-xs text-ink-dim">Колонки</span>
              <button type="button" className={btn} onClick={() => void sound()}><Volume2 size={13} /> Проверить звук</button>
            </div>
          </div>
        )}
        {step === 3 && (
          <div className="space-y-2 text-xs">
            <button type="button" className={btn} onClick={() => setWake("waiting")}>Начать проверку</button>
            {wake === "waiting" && <div className="text-ink">Скажите «Сакура»… (15 секунд)</div>}
            {wake === "ok" && <div className="text-online">Слышу! Слово «Сакура» распознаётся.</div>}
            {wake === "fail" && <div className="text-warn">Не услышала. Говорите ближе к микрофону или выберите низкую чувствительность в «Голос».</div>}
          </div>
        )}
        {step === 4 && (
          <div className="space-y-1 text-xs">
            <div>Расширение: <span className={settings?.extension_connected ? "text-online" : "text-warn"}>
              {settings?.extension_connected ? "подключено" : "не подключено"}</span></div>
            <div className="text-ink-dim">Opera GX / Chrome: «Расширения» → режим разработчика → «Загрузить распакованное» →
              C:\sakura-dev\desktop\extension. После загрузки статус обновится сам.</div>
          </div>
        )}
        {step === 5 && (
          <div className="space-y-2 text-xs">
            <div>Токен: <span className={ymSet ? "text-online" : "text-warn"}>{ymSet ? "задан" : "не задан"}</span></div>
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void saveToken(); }}>
              <input ref={tokenRef} type="password" autoComplete="off" aria-label="Токен Яндекс.Музыки" placeholder="вставьте токен" className={input + " flex-1"} />
              <button type="submit" className={btn}>Сохранить</button>
            </form>
          </div>
        )}
        {step === 6 && (
          <div aria-label="Итоговая проверка" className="space-y-1 text-xs">
            {problems.length === 0 ? (
              <div className="flex items-center gap-1.5 text-online"><CheckCircle2 size={15} /> Всё работает</div>
            ) : problems.map((p) => (
              <div key={p.text} className="flex items-center gap-2 text-warn">
                <Circle size={10} /> <span className="flex-1">{p.text}</span>
                <button type="button" className={btn} onClick={() => setStep(p.step)}>Исправить</button>
              </div>
            ))}
          </div>
        )}
      </section>
      <div className="mt-2 flex items-center justify-between">
        <button type="button" className={btn} disabled={step === 0} onClick={() => setStep(step - 1)}><ChevronLeft size={13} /> Назад</button>
        {msg && <span role="status" className="mx-2 flex-1 text-xs text-ink-dim">{msg}</span>}
        <button type="button" className={btn} disabled={step === STEPS.length - 1} onClick={() => setStep(step + 1)}>Далее <ChevronRight size={13} /></button>
      </div>
    </div>
  );
}
