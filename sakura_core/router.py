"""Роутер v3 (этап 2) — порядок разрешения, обратный v2:

    1. session   — ждём подтверждения? короткий ответ принадлежит диалогу
    2. registry  — точное совпадение фразы
    3. registry  — по границам слов, самый длинный триггер
    4. conversation — разговорные механики (translate, word_game, fortune,
       calculator, fears, games, vip_message, remember_kv, clean_slate):
       смотрят на текст, не на Decision
    5. LLM       — каталог из реестра, только то, что не попало выше
    6. разговор

В v2 LLM-классификатор стоял первым и жёг раунд-трип даже там, где ответ лежал
в таблице. Теперь он последний. Роутер ВОЗВРАЩАЕТ решение, не исполняет
(исполнение — этап 3). Контекст приходит аргументом, сам роутер никуда
за ним не ходит.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional
from sakura_core.registry import (
    Declaration,
    TriggerIndex,
    build_index,
    build_llm_catalog,
    installed_apps,
    load,
)
from sakura_core.session import Session

# LLM-классификатор: (текст, каталог) → id действия или None.
# Настоящая реализация подключается на этапе 4 (sakura_core/llm.py).
LlmClassify = Callable[[str, str], Optional[str]]


@dataclass(frozen=True)
class Decision:
    """Решение роутера без исполнения."""

    action: Optional[str]                # канонический id или None (разговор)
    source: str                          # session | registry_exact | registry_fuzzy | llm | conversation
    trigger: Optional[str] = None        # сработавший триггер (если был)
    param: Optional[str] = None          # значение параметра (если declaration.param)
    verdict: Optional[str] = None        # confirm | deny — только для source="session"
    pending_kind: Optional[str] = None   # confirm | plan | clarify — для session
    reply: Optional[object] = None       # Reply разговорного слоя (этап 5, 3/3)


def _norm_context(context) -> Optional[str]:
    """'playing:music' | {'playing': 'music'} | None → строка или None."""
    if context is None:
        return None
    if isinstance(context, str):
        return context
    if isinstance(context, dict):
        return ":".join(f"{k}:{v}" for k, v in context.items())
    raise TypeError(f"контекст должен быть строкой или словарём, получен {type(context).__name__}")


class Router:
    def __init__(self, declarations: Optional[list[Declaration]] = None, *,
                 session: Optional[Session] = None,
                 llm_classify: Optional[LlmClassify] = None,
                 wake_words: tuple[str, ...] = ("сакура",),
                 conversation: Optional[Callable] = None):
        self._declarations = list(declarations) if declarations is not None else load()
        self._index: TriggerIndex = build_index(self._declarations)
        self._by_id = {d.id: d for d in self._declarations}
        self._exact: dict[str, list[Declaration]] = {}
        for d in self._declarations:
            for trigger in d.triggers:
                self._exact.setdefault(trigger.lower(), []).append(d)
        self._catalog = build_llm_catalog(self._declarations)
        self.session = session or Session()
        self._llm = llm_classify
        self._wake = tuple(w.lower() for w in wake_words)
        # Разговорный слой (этап 5, 3/3): conversation.try_handle
        self._conversation = conversation

    # ── подготовка текста ────────────────────────────────────────────────

    def _strip_wake(self, text: str) -> str:
        """Убрать обращение-wake-слово с начала фразы: «сакура следующий трек»
        → «следующий трек». В v2 такая фраза уходила в LLM и жгла раунд-трип."""
        s = (text or "").strip()
        while True:
            low = s.lower()
            for w in self._wake:
                if low.startswith(w):
                    s = s[len(w):].lstrip(" ,.!:;-").strip()
                    break
            else:
                return s

    # ── шаги разрешения ──────────────────────────────────────────────────

    def _clarify_question(self, decl) -> str:
        """Сформулировать уточняющий вопрос для param с required='ask'."""
        param_name = decl.param.name if decl.param else "параметр"
        # Маппинг имён параметров на вопросы
        questions = {
            "query": "Какой файл искать?",
            "module_name": "Как назвать модуль?",
            "description": "Опиши проблему подробнее.",
            "filepath": "Какой файл показать?",
            "message": "Какое сообщение коммита?",
            "temp": "До какой температуры нагреть?",
        }
        return questions.get(param_name, f"Укажи {param_name}.")

    def _match_exact(self, text: str, context: Optional[str]) -> Optional[tuple[str, Declaration]]:
        tl = text.lower().strip().rstrip("!?.,;")
        for d in self._exact.get(tl, []):
            if d.context is None or d.context == context:
                # resolve без списка приложений (агент не подключён) —
                # декларация не матчится, как в TriggerIndex.match.
                if d.param is not None and d.param.resolve and not installed_apps():
                    continue
                return tl, d
        return None

    def route(self, text: str, context=None) -> Decision:
        ctx = _norm_context(context)
        cleaned = self._strip_wake(text or "")

        # 1. session — ждём ответа?
        resolved = self.session.resolve(cleaned)
        if resolved is not None:
            kind, verdict, pending = resolved
            if kind == "clarify":
                # verdict — это значение параметра; подставляем и исполняем
                return Decision(
                    action=pending.action,
                    source="session",
                    param=verdict,
                    pending_kind=kind,
                )
            return Decision(
                action=pending.action if verdict == "confirm" else None,
                source="session",
                verdict=verdict,
                pending_kind=kind,
            )

        # «Не забудь …» — просьба помнить, а не удалить память. Не отдаём
        # её ни триггеру «забудь про», ни классификатору команд удаления.
        if cleaned.lower().startswith("не забудь "):
            return Decision(None, "conversation")

        # 2. registry — точное совпадение
        exact = self._match_exact(cleaned, ctx)
        if exact is not None:
            trigger, d = exact
            # Проверяем ask param: точное совпадение + param с ask → clarify
            if d.param is not None and d.param.required == "ask":
                param_val = d.param.extract(cleaned)
                if param_val is None:
                    if self.session is not None:
                        self.session.expect(
                            "clarify",
                            action=d.id,
                            payload={"trigger": trigger, "param_name": d.param.name},
                        )
                    clarify_q = self._clarify_question(d)
                    return Decision(
                        action=None,
                        source="registry_clarify",
                        trigger=trigger,
                        pending_kind="clarify",
                        reply=clarify_q,
                    )
                return Decision(d.id, "registry_exact", trigger=trigger, param=param_val)
            return Decision(d.id, "registry_exact", trigger=trigger)

        # 3. registry — по границам слов, самый длинный триггер
        fuzzy = self._index.match(cleaned, ctx)
        if fuzzy is not None:
            trigger, d, param_value, needs_clarify = fuzzy
            if needs_clarify:
                # Параметр нужен, но отсутствует — уточняющий вопрос
                if self.session is not None:
                    self.session.expect(
                        "clarify",
                        action=d.id,
                        payload={"trigger": trigger, "param_name": d.param.name},
                    )
                clarify_q = self._clarify_question(d)
                return Decision(
                    action=None,
                    source="registry_clarify",
                    trigger=trigger,
                    pending_kind="clarify",
                    reply=clarify_q,
                )
            return Decision(d.id, "registry_fuzzy", trigger=trigger, param=param_value)

        # 4. разговорные механики — смотрят на текст, не на Decision
        if self._conversation is not None:
            reply = self._conversation(cleaned)
            if reply is not None:
                return Decision(None, "conversation", reply=reply)

        # 5. LLM — каталог из реестра; неизвестный id считаем разговором
        if self._llm is not None:
            action = self._llm(cleaned, self._catalog)
            if action and action in self._by_id:
                return Decision(action, "llm")

        # 6. разговор
        return Decision(None, "conversation")