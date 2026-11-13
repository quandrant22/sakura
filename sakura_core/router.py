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

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Union
from sakura_core.registry import (
    Declaration,
    TriggerIndex,
    build_index,
    build_llm_catalog,
    installed_apps,
    load,
)
from sakura_core.session import Session

from sakura_core.nlu import (
    IntentParse,
    LlmUnavailable,
    UnitGuard,
    find_delay,
    implied_context,
    split_units,
)

log = logging.getLogger("sakura.router")

# LLM-классификатор (прежний контракт): (текст, каталог) → (id, param) | id | None.
LlmClassify = Callable[[str, str], Awaitable[Union[Optional[str], tuple[Optional[str], Optional[str]]]]]
# Структурированный разбор: (текст, каталог, контекст) → IntentParse.
# Сбой или таймаут — исключение LlmUnavailable (это НЕ вердикт «разговор»).
LlmParse = Callable[[str, str, Optional[dict]], Awaitable[IntentParse]]

# Действия, у которых после триггера идёт свободный текст, а параметра в
# реестре нет: аргумент разбирает capabilities/vps_arguments.py из фразы.
FREE_TAIL_ACTIONS = frozenset({
    "task.add", "task.done", "reminder.add", "memory.forget",
    "steam.playtime", "steam.progress", "steam.achievements",
    "music_stats.recent", "music_stats.top",
})

# Необратимые действия питания: с отложенным временем («через час»)
# исполнять немедленно нельзя — таймера у них нет.
DEFER_SENSITIVE = {
    "system.shutdown": "Выключение",
    "system.restart": "Перезагрузку",
    "power.sleep": "Сон",
}


@dataclass(frozen=True)
class Step:
    """Один шаг плана: действие, параметр и часть фразы, из которой он взят."""

    action: str
    param: Optional[str] = None
    trigger: Optional[str] = None
    text: str = ""
    source: str = ""


@dataclass(frozen=True)
class Decision:
    """Решение роутера без исполнения."""

    action: Optional[str]                # канонический id или None (разговор)
    source: str                          # session | registry_exact | registry_fuzzy | registry_plan | registry_fallback | registry_deferred | llm | conversation
    trigger: Optional[str] = None        # сработавший триггер (если был)
    param: Optional[str] = None          # значение параметра (если declaration.param)
    verdict: Optional[str] = None        # confirm | deny — только для source="session"
    pending_kind: Optional[str] = None   # confirm | plan | clarify — для session
    reply: Optional[object] = None       # Reply разговорного слоя (этап 5, 3/3)
    # Подтверждённое «да» действие: payload ожидания (готовая команда агенту,
    # параметр, исходная фраза) — исполнить ровно то, о чём спрашивали.
    pending_payload: Optional[dict] = None
    # План из нескольких действий («включи музыку и сделай погромче») и
    # гибрид «команда + разговор». У обычного решения steps пуст; action и
    # param всегда равны первому шагу — прежний код читает их как раньше.
    steps: tuple[Step, ...] = ()
    chat_tail: Optional[str] = None      # разговорная часть гибридной фразы

    @property
    def plan(self) -> tuple[Step, ...]:
        """Шаги к исполнению: steps либо единственный шаг из action/param."""
        if self.steps:
            return self.steps
        if self.action:
            return (Step(self.action, self.param, self.trigger, "", self.source),)
        return ()

    @property
    def actions(self) -> tuple[str, ...]:
        return tuple(s.action for s in self.plan)

    @property
    def is_plan(self) -> bool:
        return len(self.steps) > 1

    @property
    def kind(self) -> str:
        """plan | hybrid | command | reply | conversation."""
        if self.is_plan:
            return "plan"
        if self.action and self.chat_tail:
            return "hybrid"
        if self.action:
            return "command"
        if self.reply is not None:
            return "reply"
        return "conversation"


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
                 llm_parse: Optional[LlmParse] = None,
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
        self._parse = llm_parse
        self._guard = UnitGuard(self._declarations, FREE_TAIL_ACTIONS)
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

    async def route(self, text: str, context=None, *, source: str | None = None,
                    on_llm: Optional[Callable[[], None]] = None,
                    dialog: Optional[dict] = None) -> Decision:
        """Разобрать текст: session → registry → механики → LLM → разговор.

        dialog — контекст хода для LLM-разбора (активное окно, что играет,
        последние реплики); локальным шагам он не нужен.

        on_llm — одноразовый хук, вызывается ТОЛЬКО если точные пути не
        сработали и дошёл шаг LLM-классификатора (п.2: голос параллельно
        классификатору стартует именно здесь).
        """
        ctx = _norm_context(context)
        cleaned = self._strip_wake(text or "")

        # 1. session — ждём ответа?
        resolved = self.session.resolve(cleaned, source=source)
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
            payload = dict(pending.payload or {})
            return Decision(
                action=pending.action if verdict == "confirm" else None,
                source="session",
                verdict=verdict,
                pending_kind=kind,
                param=payload.get("param") if verdict == "confirm" else None,
                pending_payload=payload or None,
            )

        # «Не забудь …» — просьба помнить, а не удалить память. Не отдаём
        # её ни триггеру «забудь про», ни классификатору команд удаления.
        if cleaned.lower().startswith("не забудь "):
            return Decision(None, "conversation")

        # 2–3. registry — локальный разбор без LLM: точное совпадение,
        # план из частей фразы, триггер по границам слов
        local = self._local_parse(cleaned, ctx)
        if local is not None:
            return self._hold_deferred(local, cleaned)

        # 4. разговорные механики — смотрят на текст, не на Decision
        if self._conversation is not None:
            reply = self._conversation(cleaned)
            if reply is not None:
                return Decision(None, "conversation", reply=reply)

        # 5. LLM — каталог из реестра; неизвестный id считаем разговором
        if self._parse is not None:
            if on_llm is not None:
                # Точка параллелизма (п.2): разбор и подготовка голосового
                # ответа идут одновременно.
                on_llm()
            try:
                parsed = await self._parse(cleaned, self._catalog,
                                           {"context": ctx, **(dialog or {})})
            except LlmUnavailable as e:
                # Сбой — не вердикт «разговор»: пробуем локальный мягкий разбор.
                log.warning("[router] LLM-разбор недоступен (%s) — локальный разбор", e)
                fallback = self._local_fallback(cleaned, ctx)
                if fallback is not None:
                    return self._hold_deferred(fallback, cleaned)
                return Decision(None, "conversation")
            decision = self._decision_from_parse(parsed, cleaned)
            if decision is not None:
                return self._hold_deferred(decision, cleaned)
        elif self._llm is not None:
            if on_llm is not None:
                on_llm()
            raw_decision = await self._llm(cleaned, self._catalog)
            action, param_val = None, None
            if isinstance(raw_decision, tuple):
                action = raw_decision[0]
                param_val = raw_decision[1] if len(raw_decision) > 1 else None
            elif isinstance(raw_decision, str):
                if "|" in raw_decision:
                    p1, p2 = raw_decision.split("|", 1)
                    action = p1.strip()
                    param_val = p2.strip() or None
                else:
                    action = raw_decision
            if action:
                decision = self._decision_from_parse(
                    IntentParse(actions=((action, param_val),)), cleaned)
                if decision is not None:
                    return self._hold_deferred(decision, cleaned)

        # 6. разговор
        return Decision(None, "conversation")

    # ── локальный разбор ─────────────────────────────────────────────────

    def _clarify(self, d: Declaration, trigger: Optional[str]) -> Decision:
        """Параметр нужен, но отсутствует — уточняющий вопрос и ожидание."""
        if self.session is not None:
            payload = {"param_name": d.param.name}
            if trigger:
                payload["trigger"] = trigger
            self.session.expect("clarify", action=d.id, payload=payload)
        return Decision(action=None, source="registry_clarify", trigger=trigger,
                        pending_kind="clarify", reply=self._clarify_question(d))

    def _local_parse(self, cleaned: str, ctx: Optional[str]) -> Optional[Decision]:
        # точное совпадение всей фразы
        exact = self._match_exact(cleaned, ctx)
        if exact is not None:
            trigger, d = exact
            if d.param is not None and d.param.required == "ask":
                param_val = d.param.extract(cleaned)
                if param_val is None:
                    return self._clarify(d, trigger)
                return Decision(d.id, "registry_exact", trigger=trigger, param=param_val)
            return Decision(d.id, "registry_exact", trigger=trigger)

        whole = self._index.match(cleaned, ctx)

        # несколько частей: план («А и Б») или гибрид («А, а я пока …»)
        units = split_units(cleaned)
        if len(units) > 1 and not (whole and len(split_units(whole[0])) > 1):
            plan = self._plan_from_units(units, ctx)
            if plan is not None:
                return plan

        # вся фраза — по границам слов, самый длинный триггер
        if whole is not None:
            trigger, d, param_value, needs_clarify = whole
            if self._guard.is_command(cleaned, trigger, d):
                if needs_clarify:
                    return self._clarify(d, trigger)
                return Decision(d.id, "registry_fuzzy", trigger=trigger, param=param_value)
            log.debug("[router] триггер %r внутри чужой фразы — не команда: %r",
                      trigger, cleaned)
        return None

    def _match_unit(self, text: str, ctx: Optional[str], *,
                    lenient: bool = False) -> Optional[Step]:
        """Часть фразы → шаг, если это явная команда с известным параметром."""
        if not lenient:
            exact = self._match_exact(text, ctx)
            if exact is not None:
                trigger, d = exact
                param_val = None
                if d.param is not None and d.param.required == "ask":
                    param_val = d.param.extract(text)
                    if param_val is None:
                        return None
                return Step(d.id, param_val, trigger, text, "registry_exact")
        fuzzy = self._index.match(text, ctx)
        if fuzzy is None:
            return None
        trigger, d, param_value, needs_clarify = fuzzy
        if needs_clarify:
            return None
        check = self._guard.is_plausible if lenient else self._guard.is_command
        if not check(text, trigger, d):
            return None
        return Step(d.id, param_value, trigger, text,
                    "registry_fallback" if lenient else "registry_fuzzy")

    def _steps_from_units(self, units: list[tuple[str, str]], ctx: Optional[str], *,
                          lenient: bool = False) -> tuple[list[Step], list[str]]:
        """Части фразы → (шаги, разговорные остатки)."""
        items: list[list] = []          # [текст, шаг | None, контекст совпадения]
        implied: Optional[str] = None   # контекст, созданный предыдущим шагом
        for text, sep in units:
            used_ctx = ctx
            step = self._match_unit(text, ctx, lenient=lenient)
            if step is None and implied and implied != ctx:
                step = self._match_unit(text, implied, lenient=lenient)
                used_ctx = implied
            if step is None and items and items[-1][1] is not None \
                    and self._guard.takes_free_tail(items[-1][1].action):
                # «добавь задачу купить хлеб и молоко» — «молоко» продолжает
                # свободный текст предыдущей команды, это не отдельная часть.
                merged = f"{items[-1][0]}{sep}{text}"
                again = self._match_unit(merged, items[-1][2], lenient=lenient)
                if again is not None and again.action == items[-1][1].action:
                    items[-1][0], items[-1][1] = merged, again
                    continue
            items.append([text, step, used_ctx])
            if step is not None:
                implied = implied_context(step.action, step.param) or implied
        steps = [it[1] for it in items if it[1] is not None]
        rest = [it[0] for it in items if it[1] is None]
        return steps, rest

    def _plan_from_units(self, units: list[tuple[str, str]], ctx: Optional[str], *,
                         lenient: bool = False) -> Optional[Decision]:
        steps, rest = self._steps_from_units(units, ctx, lenient=lenient)
        if not steps:
            return None
        first = steps[0]
        if len(steps) == 1 and not rest:
            return Decision(first.action, first.source, trigger=first.trigger,
                            param=first.param)
        if lenient:
            source = "registry_fallback"
        else:
            # Один шаг + разговорный остаток: вся фраза точным совпадением не была.
            source = "registry_fuzzy" if len(steps) == 1 else "registry_plan"
        return Decision(first.action, source, trigger=first.trigger, param=first.param,
                        steps=tuple(steps), chat_tail=", ".join(rest) or None)

    def _local_fallback(self, cleaned: str, ctx: Optional[str]) -> Optional[Decision]:
        """LLM недоступен: мягкий локальный разбор по частям фразы."""
        units = split_units(cleaned)
        decision = self._plan_from_units(units, ctx, lenient=True)
        if decision is None and len(units) > 1:
            decision = self._plan_from_units([(cleaned, "")], ctx, lenient=True)
        return decision

    # ── LLM-разбор → решение ─────────────────────────────────────────────

    def _decision_from_parse(self, parsed: IntentParse, cleaned: str) -> Optional[Decision]:
        """Проверить разбор по схеме реестра и собрать решение.

        Неизвестные id отбрасываются. Параметр: значение от модели, иначе —
        шаблон декларации по фразе; числовой параметр обязан содержать цифры.
        """
        steps: list[Step] = []
        ask: Optional[Declaration] = None
        for action, param_val in parsed.actions:
            d = self._by_id.get(action or "")
            if d is None:
                continue
            param_val = (param_val or "").strip() or None
            if d.param is not None:
                numeric = r"\d" in d.param.pattern and ".+" not in d.param.pattern
                if param_val and numeric and not any(ch.isdigit() for ch in param_val):
                    param_val = None
                if not param_val:
                    param_val = d.param.extract(cleaned)
                if not param_val and d.param.required == "ask":
                    ask = ask or d
                    continue
            steps.append(Step(d.id, param_val, None, cleaned, "llm"))
        if not steps:
            return self._clarify(ask, None) if ask is not None else None
        first = steps[0]
        chat_tail = cleaned if parsed.chat else None
        if len(steps) == 1 and not chat_tail:
            return Decision(first.action, "llm", param=first.param)
        return Decision(first.action, "llm", param=first.param,
                        steps=tuple(steps), chat_tail=chat_tail)

    # ── отложенные команды питания ───────────────────────────────────────

    def _hold_deferred(self, decision: Decision, cleaned: str) -> Decision:
        """«Выключи компьютер через час» — немедленно исполнять нельзя.

        Таймера у действий питания нет: вместо мгновенного выключения —
        честный ответ. Остальные шаги плана тоже не исполняются: фраза
        понята не полностью, и молча выполнить её часть было бы хуже.
        """
        for step in decision.plan:
            noun = DEFER_SENSITIVE.get(step.action)
            if noun is None:
                continue
            delay = find_delay(step.text or cleaned)
            if delay:
                log.info("[router] %s с отложенным временем %r — не исполняю",
                         step.action, delay)
                return Decision(
                    None, "registry_deferred", trigger=step.trigger,
                    reply=(f"{noun} по таймеру я пока не умею, поэтому «{delay}» "
                           f"не сработает. Скажите, когда будет пора, — сделаю сразу."))
        return decision

