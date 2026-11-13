import os
from datetime import datetime, timedelta
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    Credentials = None
    Request = None
    build = None

TOKEN_FILE = "token.json"
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']


class CalendarUnavailable(RuntimeError):
    """Календарь не подключён: нет библиотек Google или token.json."""


def unavailable_reason() -> str | None:
    """Почему календарь не подключён; None — подключён. Без сети, мгновенно."""
    if build is None:
        return "не установлены библиотеки Google API"
    if not os.path.exists(TOKEN_FILE):
        return f"нет файла {TOKEN_FILE} (не пройдена авторизация auth_calendar.py)"
    return None


def get_calendar_service():
    # Без token.json build() ушёл бы искать учётные данные по умолчанию
    # (метаданные облака) и висел несколько секунд — отказываем сразу.
    reason = unavailable_reason()
    if reason:
        raise CalendarUnavailable(reason)
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)


def get_upcoming_events(hours_ahead: int = 24) -> list:
    try:
        service = get_calendar_service()
        now = datetime.utcnow()
        time_max = now + timedelta(hours=hours_ahead)

        events_result = service.events().list(
            calendarId='primary',
            timeMin=now.isoformat() + 'Z',
            timeMax=time_max.isoformat() + 'Z',
            maxResults=10,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])
        result = []

        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'Без названия')
            description = event.get('description', '')

            if 'T' in start:
                dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                from datetime import timezone
                import pytz
                moscow = pytz.timezone('Europe/Moscow')
                dt_moscow = dt.astimezone(moscow)
                time_str = dt_moscow.strftime('%H:%M')
                date_str = dt_moscow.strftime('%d.%m')
            else:
                time_str = "весь день"
                date_str = start

            result.append({
                "summary": summary,
                "time": time_str,
                "date": date_str,
                "description": description[:100] if description else ""
            })

        return result

    except Exception:
        return []


def get_calendar_context() -> str:
    events = get_upcoming_events(hours_ahead=24)
    if not events:
        return ""

    lines = ["СОБЫТИЯ В КАЛЕНДАРЕ (ближайшие 24 часа):"]
    for e in events:
        line = f"- {e['date']} {e['time']}: {e['summary']}"
        if e['description']:
            line += f" ({e['description']})"
        lines.append(line)

    return "\n".join(lines)


def get_urgent_event() -> dict | None:
    events = get_upcoming_events(hours_ahead=2)
    if not events:
        return None

    now = datetime.now()
    for e in events:
        if e['time'] != "весь день":
            try:
                import pytz
                moscow = pytz.timezone('Europe/Moscow')
                event_time = datetime.strptime(f"{e['date']}.{now.year} {e['time']}", "%d.%m.%Y %H:%M")
                event_time = moscow.localize(event_time)
                now_moscow = datetime.now(moscow)
                diff = (event_time - now_moscow).total_seconds() / 60
                if 0 < diff <= 60:
                    e['minutes_left'] = int(diff)
                    return e
            except Exception:
                pass
    return None
