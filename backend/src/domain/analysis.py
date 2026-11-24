import json
from datetime import date, timedelta
from math import isfinite
from pathlib import Path
from collections import Counter
from math import exp, log

_SPEC = json.loads(Path(__file__).with_name("spec.json").read_text(encoding="utf-8"))


def _validate_fields(values, fields, *, defaults=False):
    result = {}
    for field in fields:
        key = field["key"]
        value = values.get(key, field.get("default") if defaults else None)
        kind = field["type"]
        if kind == "number" or kind == "integer":
            valid = type(value) in (int, float) and isfinite(value) and field["min"] <= value <= field["max"]
            valid = valid and (kind != "integer" or int(value) == value)
            if valid:
                value = int(value) if kind == "integer" else float(value)
        elif kind == "choice":
            valid = value in field["choices"]
        else:
            valid = isinstance(value, str) and 0 < len(value.strip()) <= 300
            if valid and kind == "date":
                try:
                    valid = date.fromisoformat(value).isoformat() == value
                except ValueError:
                    valid = False
            if valid:
                value = value.strip()
        if not valid:
            raise ValueError(f"「{field['label']}」格式或范围无效")
        result[key] = value
    return result


def validate(row):
    _validate_fields(row, _SPEC["fields"])


def _inputs(rows, parameters, identity="ticket"):
    clean = [_validate_fields(row, _SPEC["fields"]) for row in rows]
    if len({row[identity] for row in clean}) != len(clean):
        raise ValueError(f"存在重复的{next(field['label'] for field in _SPEC['fields'] if field['key'] == identity)}，请检查单据")
    params = _validate_fields(parameters, _SPEC["parameters"], defaults=True)
    return sorted(clean, key=lambda row: (row.get("day", ""), row[identity])), params


def _day(start, offset):
    return (date.fromisoformat(start) + timedelta(days=offset)).isoformat()


def _shown(value, places=2):
    return "—" if value is None else round(float(value), places)


def _output(headline, summary, columns, rows, metrics, chart_name, chart_unit, chart_data):
    return {
        "headline": headline,
        "summary": summary,
        "columns": [{"key": key, "label": label} for key, label in columns],
        "rows": rows,
        "metrics": [{"label": label, "value": value, "unit": unit} for label, value, unit in metrics],
        "chart": {
            "label": chart_name, "unit": chart_unit,
            "points": [{"label": str(label), "value": value} for label, value in chart_data],
        },
    }


POSITIVE, NEGATIVE, PENDING = "返染", "留样", "待判"
FIELDS = (("shade", "干湿色差"), ("ring", "样边水圈"), ("bleed", "白布沾色"))
COLUMNS = (("ticket", "色样签"), ("lot", "批号"), ("outcome", "工艺签认"),
           ("risk", "返染概率（%）"), ("decision", "抽查建议"), ("prior", "先验赔率"),
           *((key, f"{label}赔率倍数") for key, label in FIELDS), ("signal", "主要风险信号"))


def _fit(rows, alpha):
    totals = Counter(row["outcome"] for row in rows)
    if not totals[POSITIVE] or not totals[NEGATIVE]:
        raise ValueError("训练染批须同时有返染与留样两类签认")
    prior = (totals[POSITIVE] + alpha) / (totals[NEGATIVE] + alpha)
    proportions = {
        outcome: {key: (sum(row["outcome"] == outcome and row[key] == "是" for row in rows) + alpha)
                  / (total + 2 * alpha) for key, _ in FIELDS}
        for outcome, total in totals.items()
    }
    return prior, proportions


def analyze(rows, parameters):
    rows, options = _inputs(rows, parameters)
    known = [row for row in rows if row["outcome"] != PENDING]
    days = {row["lot"]: row["day"] for row in known}
    if len(days) < 3:
        raise ValueError("至少需要三个已签认的染批")
    holdout_lot = max(days, key=lambda lot: (days[lot], lot))
    train = [row for row in known if row["lot"] != holdout_lot]
    checked = [row for row in known if row["lot"] == holdout_lot]
    prior, proportions = _fit(train, options["alpha"])

    def score(row):
        factors = {}
        for key, _ in FIELDS:
            hit = proportions[POSITIVE][key]
            miss = proportions[NEGATIVE][key]
            factors[key] = hit / miss if row[key] == "是" else (1 - hit) / (1 - miss)
        log_odds = log(prior) + sum(log(value) for value in factors.values())
        chance = 100 / (1 + exp(-log_odds))
        best, label = max(FIELDS, key=lambda field: factors[field[0]])
        return {key: row[key] for key in ("ticket", "lot", "outcome")} | {
            "risk": _shown(chance), "decision": "列入复检" if chance >= options["risk"] else "常规抽查",
            "prior": _shown(prior, 3), "signal": label if factors[best] > 1 else "三项均未推高风险",
        } | {key: _shown(factor, 3) for key, factor in factors.items()}

    pending = [score(row) for row in rows if row["outcome"] == PENDING]
    evaluation = [score(row) for row in checked]
    flagged = sum(row["decision"] == "列入复检" for row in pending)
    false_negative = sum(row["outcome"] == POSITIVE and row["decision"] != "列入复检" for row in evaluation)
    false_positive = sum(row["outcome"] == NEGATIVE and row["decision"] == "列入复检" for row in evaluation)
    return _output("色样返染抽查队列", f"使用 {len(train)} 张签认色卡；整批留出 {holdout_lot} 的 {len(evaluation)} 张色卡核查。漏掉 {false_negative} 张返染签认，多查 {false_positive} 张留样。",
                   COLUMNS, pending + evaluation,
                   [("训练色样", len(train), "张"), ("留出漏查", false_negative, "张"), ("待判需复检", flagged, "张")],
                   "各待判色卡返染概率", "%", [(row["ticket"], row["risk"]) for row in pending])


def seed():
    rows = []
    for lot in range(1, 7):
        for i in range(10):
            outcome = POSITIVE if i in (3, 4, 7, 8) else NEGATIVE
            shade = (i in (3, 4, 7, 8, lot % 3))
            ring = (i in (0, 4, 7, 8))
            bleed = (i in (3, 4, 7)) != (lot == 6 and i == 7)
            rows.append({"ticket": f"CY-{lot}-{i + 1:02}", "lot": f"D{lot:02}",
                         "day": _day("2026-11-02", 3 * (lot - 1)), "outcome": outcome,
                         **{key: "是" if condition else "否" for key, condition in zip(("shade", "ring", "bleed"), (shade, ring, bleed))}})
    for i, votes in enumerate((("否", "否", "否"), ("是", "否", "是"), ("否", "是", "是"), ("是", "是", "否")), 1):
        rows.append({"ticket": f"CY-P{i:02}", "lot": "D07", "day": "2026-11-21", "outcome": PENDING,
                     **dict(zip(("shade", "ring", "bleed"), votes))})
    return rows
