"""
Оценка качества извлечения против эталона.

По каждому полю считаются три величины:

    точность  — доля верных среди тех, что метод заполнил;
    полнота   — доля верных среди тех, что в договоре есть;
    ложные заполнения — доля случаев, когда поля в договоре нет,
        а метод его выдумал.

Последнее вынесено отдельно, потому что это самая опасная ошибка.
Пропущенное поле юрист заметит. Выдуманное — нет.

    python src/evaluate.py
    python src/evaluate.py --show 5     # разбор первых ошибок
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extract import extract  # noqa: E402

FIELDS = ["party_a", "inn_a", "party_b", "inn_b", "subject", "amount",
          "vat", "prepay_percent", "penalty", "term_days", "law", "forum"]


def norm(v):
    if v is None:
        return None
    if isinstance(v, str):
        return " ".join(v.lower().split()).rstrip(".")
    return v


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default="data/contracts.json")
    ap.add_argument("--show", type=int, default=0)
    args = ap.parse_args()

    docs = json.load(open(args.input, encoding="utf-8"))

    stat = {f: {"tp": 0, "filled": 0, "present": 0, "false_fill": 0,
                "absent": 0} for f in FIELDS}
    errors = {f: [] for f in FIELDS}

    contr_tp = contr_fp = contr_fn = 0
    noisy_hits = {"noisy": [0, 0], "clean": [0, 0]}

    for d in docs:
        got, flags = extract(d["text"])
        truth = d["truth"]
        bucket = "noisy" if truth["noisy"] else "clean"

        for f in FIELDS:
            exp, act = norm(truth.get(f)), norm(got.get(f))
            if exp is None:
                stat[f]["absent"] += 1
                if act is not None:
                    stat[f]["false_fill"] += 1
                    if len(errors[f]) < 5:
                        errors[f].append((truth["id"], "выдумано", act))
            else:
                stat[f]["present"] += 1
                noisy_hits[bucket][1] += 1
                if act is not None:
                    stat[f]["filled"] += 1
                if act == exp:
                    stat[f]["tp"] += 1
                    noisy_hits[bucket][0] += 1
                elif len(errors[f]) < 5:
                    errors[f].append((truth["id"], exp, act))

        if truth["contradiction"] and flags["price_contradiction"]:
            contr_tp += 1
        elif truth["contradiction"]:
            contr_fn += 1
        elif flags["price_contradiction"]:
            contr_fp += 1

    print(f"договоров: {len(docs)}\n")
    print(f"{'поле':>16} {'точность':>9} {'полнота':>8} {'ложных':>7} "
          f"{'есть':>6} {'нет':>5}")
    for f in FIELDS:
        s = stat[f]
        prec = s["tp"] / s["filled"] if s["filled"] else 0.0
        rec = s["tp"] / s["present"] if s["present"] else 0.0
        ff = s["false_fill"] / s["absent"] if s["absent"] else 0.0
        print(f"{f:>16} {prec:>9.3f} {rec:>8.3f} {ff:>7.3f} "
              f"{s['present']:>6} {s['absent']:>5}")

    tot_tp = sum(s["tp"] for s in stat.values())
    tot_present = sum(s["present"] for s in stat.values())
    tot_filled = sum(s["filled"] for s in stat.values())
    tot_ff = sum(s["false_fill"] for s in stat.values())
    tot_absent = sum(s["absent"] for s in stat.values())
    print(f"\n{'ИТОГО':>16} {tot_tp / tot_filled:>9.3f} "
          f"{tot_tp / tot_present:>8.3f} "
          f"{tot_ff / tot_absent if tot_absent else 0:>7.3f}")

    print(f"\nПротиворечие цены: найдено {contr_tp}, пропущено {contr_fn}, "
          f"ложных {contr_fp}")

    for b in ("clean", "noisy"):
        hit, tot = noisy_hits[b]
        label = "чистые" if b == "clean" else "с шумом"
        print(f"Полнота на {label:>8}: {hit / tot if tot else 0:.3f} "
              f"({tot} полей)")

    if args.show:
        print("\nПримеры расхождений:")
        for f in FIELDS:
            if errors[f]:
                print(f"\n  {f}:")
                for i, (did, exp, act) in enumerate(errors[f][:args.show]):
                    print(f"    №{did}: ожидалось {exp!r}, получено {act!r}")


if __name__ == "__main__":
    main()
