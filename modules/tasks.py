import json
import os
import re
from datetime import datetime, date, timedelta

TASKS_FILE = "memory/tasks.json"

def load_tasks() -> list:
    if not os.path.exists(TASKS_FILE):
        return []
    try:
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_tasks(tasks: list):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)

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

def get_due_tasks() -> list:
    """Задачи которые пора выполнить — просроченные или наступившие"""
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
                except:
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
        except:
            pass

    return upcoming

def get_tasks_context() -> str:
    """Контекст задач для промпта Сакуры"""
    tasks = load_tasks()
    today = str(date.today())
    now = datetime.now()
    active = [t for t in tasks if not t.get("done")]
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
                    except:
                        pass
        time_str = f" в {due_time}" if due_time else ""
        date_str = f" {due_date}" if due_date else ""
        lines.append(f"- {t['text']}{date_str}{time_str}{status}")

    return "\n".join(lines)

def extract_tasks_from_text(text: str) -> list:
    """Извлекает задачи из текста разговора"""
    tasks_found = []
    text_lower = text.lower()
    today = date.today()

    task_triggers = [
        "напомни", "не забудь", "нужно", "надо", "запомни что",
        "завтра", "послезавтра", "в понедельник", "во вторник",
        "в среду", "в четверг", "в пятницу"
    ]

    if not any(t in text_lower for t in task_triggers):
        return []

    # Определяем дату
    due_date = None
    if "завтра" in text_lower:
        due_date = str(today + timedelta(days=1))
    elif "послезавтра" in text_lower:
        due_date = str(today + timedelta(days=2))
    elif "сегодня" in text_lower:
        due_date = str(today)
    else:
        weekdays = {
            "понедельник": 0, "вторник": 1, "среду": 2, "среда": 2,
            "четверг": 3, "пятницу": 4, "пятница": 4,
            "субботу": 5, "суббота": 5, "воскресенье": 6
        }
        for day_name, day_num in weekdays.items():
            if day_name in text_lower:
                days_ahead = (day_num - today.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                due_date = str(today + timedelta(days=days_ahead))
                break

    # Определяем время
    due_time = None
    time_match = re.search(r'в\s+(\d{1,2})(?:[:\.](\d{2}))?\s*(?:час|утра|дня|вечера|ночи)?', text_lower)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        if "вечера" in text_lower and hour < 12:
            hour += 12
        due_time = f"{hour:02d}:{minute:02d}"

    if due_date or due_time:
        tasks_found.append({
            "text": text[:200],
            "due_date": due_date,
            "due_time": due_time
        })

    return tasks_found