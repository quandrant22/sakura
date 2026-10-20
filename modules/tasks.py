import json
import os
import re
from datetime import datetime, date, timedelta

from modules.jsonio import save_json

TASKS_FILE = "memory/tasks.json"

def load_tasks() -> list:
    if not os.path.exists(TASKS_FILE):
        return []
    try:
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_tasks(tasks: list):
    save_json(TASKS_FILE, tasks)

def add_task(text: str, due_date: str = None, due_time: str = None):
    tasks = load_tasks()
    task = {
        "id": int(datetime.now().timestamp()),
        "text": text,
        "due_date": due_date,
        "due_time": due_time,
        "created": str(datetime.now()),
        "done": False,
        "notified": False
    }
    tasks.append(task)
    save_tasks(tasks)
    return task

def complete_task(task_id: int):
    tasks = load_tasks()
    for t in tasks:
        if t["id"] == task_id:
            t["done"] = True
    save_tasks(tasks)

def mark_notified(task_id: int):
    tasks = load_tasks()
    for t in tasks:
        if t["id"] == task_id:
            t["notified"] = True
    save_tasks(tasks)

ARCHIVE_FILE = "memory/tasks_archive.json"
ARCHIVE_AFTER_H = 24      # просрочено дольше — в архив, в промпт не идёт


def _due_dt(t: dict):
    d = t.get("due_date")
    if not d:
        return None
    try:
        h, m = map(int, (t.get("due_time") or "23:59").split(":"))
        return datetime.strptime(d, "%Y-%m-%d").replace(hour=h, minute=m)
    except Exception:
        return None


def archive_overdue(now: datetime | None = None) -> int:
    """Невыполненные задачи, просроченные > ARCHIVE_AFTER_H часов, → архив."""
    now = now or datetime.now()
    tasks = load_tasks()
    keep, old = [], []
    for t in tasks:
        due = _due_dt(t)
        if (not t.get("done") and due is not None
                and now - due > timedelta(hours=ARCHIVE_AFTER_H)):
            old.append(t)
        else:
            keep.append(t)
    if old:
        try:
            with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
                arch = json.load(f)
        except Exception:
            arch = []
        arch.extend({**t, "archived": str(now)} for t in old)
        save_json(ARCHIVE_FILE, arch)
        save_tasks(keep)
    return len(old)


def get_due_tasks() -> list:
    """Задачи которые пора выполнить — просроченные или наступившие"""
    archive_overdue()
    tasks = load_tasks()
    today = str(date.today())
    now = datetime.now()
    due = []

    for t in tasks:
        if t.get("done") or t.get("notified"):
            continue
        due_date = t.get("due_date")
        if not due_date:
            continue

        if due_date < today:
            # Просрочена
            due.append(t)
        elif due_date == today:
            due_time = t.get("due_time")
            if due_time:
                try:
                    h, m = map(int, due_time.split(":"))
                    task_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    if now >= task_dt:
                        due.append(t)
                except Exception:
                    due.append(t)
            else:
                due.append(t)

    return due

def get_upcoming_tasks(hours_ahead: int = 2) -> list:
    """Задачи которые наступят в ближайшие N часов"""
    tasks = load_tasks()
    today = str(date.today())
    now = datetime.now()
    upcoming = []

    for t in tasks:
        if t.get("done") or t.get("notified"):
            continue
        due_date = t.get("due_date")
        due_time = t.get("due_time")
        if not due_date or not due_time:
            continue
        if due_date != today:
            continue
        try:
            h, m = map(int, due_time.split(":"))
            task_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            diff = (task_dt - now).total_seconds() / 3600
            if 0 < diff <= hours_ahead:
                upcoming.append(t)
        except Exception:
            pass

    return upcoming

def get_tasks_context() -> str:
    """Контекст задач для промпта Сакуры: только живые — не выполненные, не
    напомненные и не просроченные больше суток."""
    archive_overdue()
    tasks = load_tasks()
    today = str(date.today())
    now = datetime.now()
    active = [t for t in tasks if not t.get("done") and not t.get("notified")]
    if not active:
        return ""

    lines = ["ЗАДАЧИ И НАПОМИНАНИЯ:"]
    for t in active:
        due_date = t.get("due_date", "")
        due_time = t.get("due_time", "")
        status = ""
        if due_date:
            if due_date < today:
                status = " [ПРОСРОЧЕНО]"
            elif due_date == today:
                status = " [СЕГОДНЯ]"
                if due_time:
                    try:
                        h, m = map(int, due_time.split(":"))
                        task_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                        mins_left = int((task_dt - now).total_seconds() / 60)
                        if mins_left > 0:
                            status = f" [через {mins_left} мин]"
                        else:
                            status = " [СЕЙЧАС]"
                    except Exception:
                        pass
        time_str = f" в {due_time}" if due_time else ""
        date_str = f" {due_date}" if due_date else ""
        lines.append(f"- {t['text']}{date_str}{time_str}{status}")

    return "\n".join(lines)

_WEEKDAYS = {
    "понедельник": 0, "вторник": 1, "среду": 2, "среда": 2,
    "четверг": 3, "пятницу": 4, "пятница": 4,
    "субботу": 5, "суббота": 5, "воскресенье": 6,
}
_TIME_RE = re.compile(r'в\s+(\d{1,2})(?:[:\.](\d{2}))?(?:\s*(?:час\w*|утра|дня|вечера|ночи))?')


def parse_due(text: str, today: date | None = None, now: datetime | None = None) -> tuple:
    """(due_date, due_time) из явной просьбы «напомни завтра в 10 …».
    Нет ни даты, ни времени → (None, None). Время без даты — сегодня,
    а если оно уже прошло, то завтра."""
    today = today or date.today()
    now = now or datetime.now()
    tl = (text or "").lower()
    due_date = None
    if "послезавтра" in tl:
        due_date = str(today + timedelta(days=2))
    elif "завтра" in tl:
        due_date = str(today + timedelta(days=1))
    elif "сегодня" in tl:
        due_date = str(today)
    else:
        for name, num in _WEEKDAYS.items():
            if name in tl:
                due_date = str(today + timedelta(days=(num - today.weekday()) % 7 or 7))
                break
    due_time = None
    m = _TIME_RE.search(tl)
    if m and int(m.group(1)) < 24:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        if ("вечера" in tl or "дня" in tl) and 1 <= hour < 12:
            hour += 12
        if minute < 60:
            due_time = f"{hour:02d}:{minute:02d}"
    if due_time and not due_date:
        h, mi = map(int, due_time.split(":"))
        later = now.replace(hour=h, minute=mi, second=0, microsecond=0) > now
        due_date = str(today if later else today + timedelta(days=1))
    return due_date, due_time


def clean_task_text(text: str) -> str:
    """Текст задачи без «напомни», даты и времени."""
    t = re.sub(r'(?i)^\s*напомни(?:те)?(?:\s+мне)?\s*', '', text or '')
    t = re.sub(r'(?i)\b(послезавтра|завтра|сегодня)\b', '', t)
    t = re.sub(r'(?i)\b(?:в|во)\s+(?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)\b', '', t)
    t = _TIME_RE.sub('', t)
    return re.sub(r'\s{2,}', ' ', t).strip(' ,.-') or (text or '').strip()
