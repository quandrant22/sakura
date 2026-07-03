"""
modules/calculator.py — голосовой калькулятор без LLM.
Обрабатывает арифметику, проценты, конвертацию единиц.
"""

import re
import math

# ── Операторы ──────────────────────────────────────────────────────

_OPS = {
    "плюс":        "+",
    "минус":       "-",
    "на":          "*",
    "умножить на": "*",
    "разделить на": "/",
    "делить на":   "/",
    "процент":     "%",
}

# ── Конвертация единиц ─────────────────────────────────────────────

_UNIT_CONV = {
    # длина
    ("километр", "метры"): 1000,
    ("метр", "сантиметры"): 100,
    ("сантиметр", "миллиметры"): 10,
    # вес
    ("килограмм", "грамм"): 1000,
    ("грамм", "миллиграммы"): 1000,
    # температура — отдельно
}


def _try_eval(a: float, op: str, b: float) -> float | None:
    if op == "+":
        return a + b
    elif op == "-":
        return a - b
    elif op == "*":
        return a * b
    elif op == "/":
        return a / b if b != 0 else None
    elif op == "%":
        return a * b / 100
    return None


def _format_result(n: float) -> str:
    if n == int(n) and abs(n) < 1e15:
        return str(int(n))
    if abs(n) < 0.001 or abs(n) > 1e9:
        return f"{n:.2e}"
    r = round(n, 6)
    return str(r).rstrip("0").rstrip(".") if "." in str(r) else str(r)


# ── Температура ────────────────────────────────────────────────────

_TEMP_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*градус(?:ов|а|ов\s+а)?\s*(?:по\s+)?(c|f|celsius|fahrenheit|фаренгейт|цельси[юяй])",
    re.IGNORECASE,
)


def _convert_temp(text: str) -> str | None:
    m = _TEMP_RE.search(text)
    if not m:
        return None
    val = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    if unit in ("c", "celsius", "цельсий", "цельсия", "цельсию", "цельсия"):
        result = val * 9 / 5 + 32
        return f"{_format_result(val)}°C = {_format_result(result)}°F"
    else:
        result = (val - 32) * 5 / 9
        return f"{_format_result(val)}°F = {_format_result(result)}°C"


# ── Проценты ───────────────────────────────────────────────────────

_PCT1 = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*процент(?:ов|а)?\s*(?:от\s+)?(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_PCT2 = re.compile(
    r"сколько\s+(?:процент(?:ов|а)?)\s*(\d+(?:[.,]\d+)?)\s*(?:от|из)\s+(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_PCT3 = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:от|из)\s+(\d+(?:[.,]\d+)?)\s*процент",
    re.IGNORECASE,
)
_PCT4 = re.compile(
    r"процент\s+(?:от\s+)?(\d+(?:[.,]\d+)?)\s*[-—]\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_PCT5 = re.compile(
    r"процент(?:ов|а)?\s+(?:от\s+)?(\d+(?:[.,]\d+)?)\s+(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)


def _try_percent(text: str) -> str | None:
    for pat in (_PCT1, _PCT2, _PCT3):
        m = pat.search(text)
        if m:
            a, b = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
            result = a * b / 100
            return f"{_format_result(a)}% от {_format_result(b)} = {_format_result(result)}"
    m = _PCT4.search(text)
    if m:
        a, b = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
        result = a * b / 100
        return f"{_format_result(a)}% от {_format_result(b)} = {_format_result(result)}"
    m = _PCT5.search(text)
    if m:
        # "процент от X Y" = Y% от X
        base = float(m.group(1).replace(",", "."))
        pct = float(m.group(2).replace(",", "."))
        result = base * pct / 100
        return f"{_format_result(pct)}% от {_format_result(base)} = {_format_result(result)}"
    return None


# ── Корень / степень ───────────────────────────────────────────────

_SQRT_RE = re.compile(r"(?:корень|квадратный\s+корень)\s+(?:из\s+)?(\d+(?:[.,]\d+)?)", re.IGNORECASE)
_POW_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:в\s+степени|в\s+степень|\^|\*\*)\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)


def _try_special(text: str) -> str | None:
    m = _SQRT_RE.search(text)
    if m:
        val = float(m.group(1).replace(",", "."))
        return f"Корень из {_format_result(val)} = {_format_result(math.sqrt(val))}"
    m = _POW_RE.search(text)
    if m:
        a, b = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
        return f"{_format_result(a)}^{_format_result(b)} = {_format_result(a ** b)}"
    return None


# ── Основной парсер ────────────────────────────────────────────────

_NUM = r"(\d+(?:[.,]\d+)?)"

# Паттерны для арифметики: "134 на 7", "5 плюс 3", "10 минус 3"
_ARITH_PATTERNS = [
    re.compile(f"{_NUM}\\s+(?:на|умножить\\s+на)\\s+{_NUM}", re.I),
    re.compile(f"{_NUM}\\s+плюс\\s+{_NUM}", re.I),
    re.compile(f"{_NUM}\\s+минус\\s+{_NUM}", re.I),
    re.compile(f"{_NUM}\\s+(?:разделить\\s+на|делить\\s+на)\\s+{_NUM}", re.I),
    re.compile(f"{_NUM}\\s*[/\\*\\+\\-]\\s*{_NUM}", re.I),
]


def _detect_op(text: str) -> str | None:
    tl = text.lower()
    if "на" in tl and re.search(rf"{_NUM}\\s+на\\s+{_NUM}", tl):
        return "*"
    if "плюс" in tl:
        return "+"
    if "минус" in tl:
        return "-"
    if "разделить" in tl or "делить" in tl:
        return "/"
    if "/" in text:
        return "/"
    if "*" in text or "на" in text:
        return "*"
    if "+" in text:
        return "+"
    if "-" in text:
        return "-"
    return None


def calculate(text: str) -> str | None:
    """
    Пытается вычислить выражение из голосового текста.
    Возвращает строку-ответ или None если не распознано.
    """
    tl = text.lower().strip().rstrip(".?!")

    # Если сообщение длинное — это не запрос калькулятора
    if len(tl) > 40:
        return None

    # Температура
    temp = _convert_temp(tl)
    if temp:
        return temp

    # Проценты
    pct = _try_percent(tl)
    if pct:
        return pct

    # Корень / степень
    spec = _try_special(tl)
    if spec:
        return spec

    # Арифметика
    op = _detect_op(tl)
    if op:
        for pat in _ARITH_PATTERNS:
            m = pat.search(tl)
            if m:
                a = float(m.group(1).replace(",", "."))
                b = float(m.group(2).replace(",", "."))
                result = _try_eval(a, op, b)
                if result is not None:
                    op_word = {"+": "плюс", "-": "минус", "*": "умножить на", "/": "разделить на", "%": "процент"}[op]
                    return f"{_format_result(a)} {op_word} {_format_result(b)} = {_format_result(result)}"

    return None
