"""Сверка вывода ProVerif с expected.json (scripts/check_proverif.py)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_proverif", ROOT / "scripts" / "check_proverif.py")
cp = importlib.util.module_from_spec(_spec)
sys.modules["check_proverif"] = cp      # dataclass ищет модуль в sys.modules
_spec.loader.exec_module(cp)

EXPECTED = json.loads((ROOT / "docs/security/proverif/expected.json").read_text(encoding="utf-8"))


def _output(values: list[str], weak: dict[str, str] | None = None, noise: bool = True) -> str:
    lines = ["Linear part:", "Completing...", "-- Query not attacker(payload_c[]) in process 1."] if noise else []
    for i, v in enumerate(values):
        tail = "cannot be proved." if v == "cannot be proved" else f"is {v}."
        lines.append(f"RESULT inj-event(ServerDone(C,S)) ==> inj-event(ClientStarted(C,S,e1)) [{i}] {tail}")
        lines.append(f"Query inj-event(...) is {v}.")    # сводка без RESULT не считается
    for name, v in (weak or {}).items():
        lines.append(f"RESULT Weak secret {name} is {v}.")
    return "\n".join(lines)


def _expected_output(model: str) -> str:
    plain = [e["expect"] for e in EXPECTED[model] if "weaksecret" not in e]
    weak = {e["weaksecret"]: e["expect"] for e in EXPECTED[model] if "weaksecret" in e}
    return _output(plain, weak)


def test_expected_matches_formal_table():
    formal = (ROOT / "docs/security/FORMAL.md").read_text(encoding="utf-8")
    for model, prefix in cp.FORMAL_PREFIX.items():
        for e in EXPECTED[model]:
            line = next(ln for ln in formal.splitlines() if ln.startswith(f"| {prefix} {e['id']} |"))
            assert line.split("|")[-3].strip().strip("*").startswith(e["expect"]), line


def test_parse_plain_and_weak():
    plain, weak = cp.parse_results(_output(["true", "false", "cannot be proved"], {"psk_qr": "true"}))
    assert plain == ["true", "false", "cannot be proved"]
    assert weak == {"psk_qr": "true"}


def test_all_expected_is_ok(tmp_path):
    for model in cp.FORMAL_PREFIX:
        (tmp_path / f"{model}.txt").write_text(_expected_output(model), encoding="utf-8")
    assert cp.main(["--results", str(tmp_path)]) == 0


def test_weaksecret_matched_by_name_not_order(tmp_path):
    (tmp_path / "ik_core.txt").write_text(_expected_output("ik_core"), encoding="utf-8")
    plain = [e["expect"] for e in EXPECTED["xxpsk3_auth"] if "weaksecret" not in e]
    text = _output(plain[:2]) + "\nRESULT Weak secret psk_words is false.\nRESULT Weak secret psk_qr is true.\n" \
        + _output(plain[2:], noise=False)
    (tmp_path / "xxpsk3_auth.txt").write_text(text, encoding="utf-8")
    assert cp.main(["--results", str(tmp_path)]) == 0


def test_divergence_fails(tmp_path, capsys):
    (tmp_path / "ik_core.txt").write_text(_expected_output("ik_core").replace("[0] is true", "[0] is false"), encoding="utf-8")
    (tmp_path / "xxpsk3_auth.txt").write_text(_expected_output("xxpsk3_auth"), encoding="utf-8")
    assert cp.main(["--results", str(tmp_path)]) == 1
    assert "ik_core Q1: ожидалось true, получено false" in capsys.readouterr().out


def test_cannot_be_proved_and_missing_are_divergence(tmp_path, capsys):
    vals = [e["expect"] for e in EXPECTED["ik_core"]]
    vals[2] = "cannot be proved"
    (tmp_path / "ik_core.txt").write_text(_output(vals[:-1]), encoding="utf-8")   # последний не завершился
    assert cp.main(["--results", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "ik_core Q3: ожидалось true, получено cannot be proved" in out
    assert "ik_core Q10: ожидалось false, получено нет вывода" in out
    assert "нет results/xxpsk3_auth.txt" in out


def test_update_formal_fills_actual_column():
    formal = (ROOT / "docs/security/FORMAL.md").read_text(encoding="utf-8")
    rows = [cp.Row("ik_core", "Q1", "true", "true"), cp.Row("xxpsk3_auth", "Q6", "false", "true")]
    new = cp.update_formal(formal, rows)
    q1 = next(ln for ln in new.splitlines() if ln.startswith("| ik Q1 |"))
    q8 = next(ln for ln in new.splitlines() if ln.startswith("| xx Q6 |"))
    assert q1.endswith("| true (совпало) |")
    assert q8.endswith("| true (**РАСХОЖДЕНИЕ** → FINDINGS.md) |")
    assert new.count(cp.PENDING) == formal.count(cp.PENDING) - 2


def test_open_queries_outside_variants_and_marked_in_formal():
    formal = (ROOT / "docs/security/FORMAL.md").read_text(encoding="utf-8")
    for model, prefix in (("ik", "ik"), ("xxpsk3", "xx")):
        variant = next(v for v, p in cp.FORMAL_PREFIX.items() if p == prefix)
        ids = {e["id"] for e in EXPECTED[variant]}
        for q in EXPECTED["_open"][model]:
            assert q not in ids
            line = next(ln for ln in formal.splitlines() if ln.startswith(f"| {prefix} {q} |"))
            assert "FINDINGS" in line.split("|")[-2], line
        assert len(ids) + len(EXPECTED["_open"][model]) == 10


def test_variants_build_from_sources(tmp_path):
    spec = importlib.util.spec_from_file_location("proverif_variants", ROOT / "scripts" / "proverif_variants.py")
    pv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pv)
    assert set(pv.VARIANTS) == set(cp.FORMAL_PREFIX)
    for name, (_src, drop, keep) in pv.VARIANTS.items():
        text = pv.build(name)
        assert len(pv.queries(text)) == len(keep) == len(EXPECTED[name])
        assert [f"Q{i}" for i in keep] == [e["id"] for e in EXPECTED[name]]
        assert not any(line in text for line in drop)
    core = pv.build("ik_core")
    assert "skK), exp(gen, skC)" not in core.split("\nprocess", 1)[1]
    assert "phase 1" in core          # прямая секретность остаётся в ядре
