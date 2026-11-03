// Язык интерфейса ru/en: язык — настройка ядра language («ru» по умолчанию). Переведены меню,
// заголовки экранов, баннеры связи и общие состояния; остальное — по мере перевода (ключ = русский текст).
import { useApp } from "./store";

export type Lang = "ru" | "en";

const EN: Record<string, string> = {
  "Главная": "Home", "Устройства": "Devices", "Сценарии": "Scenarios", "Память": "Memory",
  "Настройки": "Settings", "Профиль": "Profile",
  "Нет связи с ядром Сакуры — переподключаюсь…": "No connection to Sakura core — reconnecting…",
  "Нет связи с сервером: голосовые ответы недоступны, управление компьютером работает.":
    "Server is unreachable: voice replies are unavailable, PC control still works.",
  "Сервер не поддерживает": "Not supported by the server",
  "Сохранить": "Save", "Удалить": "Delete", "Отмена": "Cancel", "Поиск": "Search", "Повторить": "Retry",
  "Загрузка…": "Loading…", "Пусто": "Empty", "Язык": "Language",
};

export function translate(text: string, lang: Lang): string {
  return lang === "en" ? EN[text] ?? text : text;
}

export function useT(): (text: string) => string {
  const lang = useApp((s) => (s.settings?.language === "en" ? "en" : "ru")) as Lang;
  return (text) => translate(text, lang);
}
