"""
Генератор синтетических договоров с известной разметкой.

Договоры собираются из шаблонов четырёх типов: поставка, оказание услуг,
подряд, аренда. Для каждого известно, что именно в нём написано, поэтому
качество извлечения считается против эталона, а не оценивается на глаз.

В данные намеренно заложено то, что ломает извлечение по правилам:

    разное выражение одного поля — цена как «1 000 000 (один миллион)
        рублей», «1 млн руб.», «1 000 000,00 руб., в том числе НДС 20%»,
        «в размере, определённом приложением № 1»;
    отсутствующие поля — примерно в каждом седьмом договоре применимое
        право или порядок разрешения споров не указаны вовсе, и метод
        обязан вернуть пустоту, а не догадку;
    противоречия — сумма в тексте расходится с суммой в приложении;
    шум распознавания — подмена похожих символов, переносы, неразрывные
        пробелы внутри чисел.

Все тексты вымышлены. Совпадения с существующими договорами случайны.

    python src/generate.py --contracts 600 --seed 42
"""

import argparse
import json
import random

TYPES = {
    "поставка": {
        "sides": ("Поставщик", "Покупатель"),
        "subject": [
            "поставка товара согласно спецификации",
            "поставка оборудования и комплектующих",
            "поставка расходных материалов партиями",
        ],
    },
    "услуги": {
        "sides": ("Исполнитель", "Заказчик"),
        "subject": [
            "оказание консультационных услуг",
            "оказание услуг по техническому обслуживанию",
            "оказание услуг по сопровождению информационной системы",
        ],
    },
    "подряд": {
        "sides": ("Подрядчик", "Заказчик"),
        "subject": [
            "выполнение строительно-монтажных работ",
            "выполнение ремонтных работ на объекте",
            "выполнение проектных работ",
        ],
    },
    "аренда": {
        "sides": ("Арендодатель", "Арендатор"),
        "subject": [
            "передача во временное владение и пользование нежилого помещения",
            "аренда складского помещения",
            "аренда офисного помещения",
        ],
    },
}

FORMS = ["ООО", "АО", "ПАО", "ИП"]
NAMES = ["Вектор", "Гранит", "Меридиан", "Атлант", "Прогресс", "Ориент",
         "Каскад", "Магистраль", "Сфера", "Триумф", "Эталон", "Астра",
         "Континент", "Партнёр", "Ресурс", "Стандарт"]

UNITS = ["рублей", "руб.", "рублей 00 копеек"]

FORUMS = [
    "Арбитражный суд города Москвы",
    "Арбитражный суд Санкт-Петербурга и Ленинградской области",
    "Арбитражный суд Свердловской области",
    "по месту нахождения истца",
]

LAWS = [
    "законодательство Российской Федерации",
    "право Российской Федерации",
    "материальное право Российской Федерации",
]

ONES = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь",
        "восемь", "девять"]


def num_words(n):
    """Очень грубая запись числа прописью — достаточно для миллионов."""
    if n % 1_000_000 == 0 and n // 1_000_000 < 10:
        m = n // 1_000_000
        tail = "миллион" if m == 1 else ("миллиона" if m < 5 else "миллионов")
        return f"{ONES[m]} {tail}"
    if n % 1000 == 0:
        return f"{n // 1000} тысяч"
    return str(n)


def money(rng, amount, vat):
    """
    Одно и то же значение цены разными способами.

    Возвращает текст и фактически заявленную в нём ставку НДС: в части
    формулировок ставка не называется вовсе, и тогда эталон обязан быть
    пустым. Первая версия записывала ставку в разметку всегда, из-за чего
    метод штрафовался за то, что не выдумывал отсутствующее.
    """
    grouped = f"{amount:,}".replace(",", "\u00a0")   # неразрывный пробел
    plain = f"{amount:,}".replace(",", " ")
    choice = rng.randrange(6)
    if choice == 0:
        return f"{plain} ({num_words(amount)}) {rng.choice(UNITS)}", None
    if choice == 1:
        return f"{grouped} руб.", None
    if choice == 2:
        return f"{plain},00 руб., в том числе НДС {vat}%", vat
    if choice == 3:
        if amount % 1_000_000 == 0:
            return f"{amount // 1_000_000} млн руб.", None
        return f"{plain} руб.", None
    if choice == 4:
        return f"{plain} рублей, НДС не облагается", 0
    return f"{plain} руб. (включая НДС {vat}%)", vat


def party(rng):
    form = rng.choice(FORMS)
    name = rng.choice(NAMES)
    inn = str(rng.randrange(10 ** 9, 10 ** 10))
    return f'{form} «{name}»', inn


def ocr_noise(rng, text):
    """Подмена похожих символов и разрывы слов переносом."""
    subs = {"о": "0", "О": "0", "З": "3", "з": "3", "l": "1", "б": "6"}
    chars = list(text)
    for _ in range(rng.randint(2, 6)):
        i = rng.randrange(len(chars))
        if chars[i] in subs:
            chars[i] = subs[chars[i]]
    text = "".join(chars)
    # перенос внутри слова
    words = text.split(" ")
    for _ in range(rng.randint(1, 3)):
        i = rng.randrange(len(words))
        w = words[i]
        if len(w) > 7:
            k = len(w) // 2
            words[i] = w[:k] + "-\n" + w[k:]
    return " ".join(words)


def build(rng, idx, hard=False):
    kind = rng.choice(list(TYPES))
    spec = TYPES[kind]
    a_role, b_role = spec["sides"]
    a_name, a_inn = party(rng)
    b_name, b_inn = party(rng)
    subject = rng.choice(spec["subject"])

    amount = rng.choice([500_000, 750_000, 1_000_000, 1_250_000, 2_000_000,
                         3_000_000, 4_500_000, 7_000_000])
    vat = rng.choice([20, 20, 20, 10])
    prepay = rng.choice([0, 15, 30, 30, 50])
    penalty = rng.choice(["0,1", "0,05", "0,2", "1/300 ключевой ставки"])
    days = rng.choice([30, 45, 60, 90, 120, 180])

    truth = {
        "id": idx, "kind": kind,
        "party_a": a_name, "inn_a": a_inn,
        "party_b": b_name, "inn_b": b_inn,
        "subject": subject,
        "amount": amount, "vat": None,
        "prepay_percent": prepay, "penalty": penalty, "term_days": days,
        "law": None, "forum": None,
        "contradiction": False,
    }

    lines = [f"ДОГОВОР № {100 + idx}/{rng.randrange(20, 26)}",
             "г. Москва"]
    lines.append(
        f"{a_name} (ИНН {a_inn}), именуемое в дальнейшем «{a_role}», "
        f"и {b_name} (ИНН {b_inn}), именуемое в дальнейшем «{b_role}», "
        f"заключили настоящий договор о нижеследующем.")
    if hard and rng.random() < 0.4:
        lines.append(f"1. Предмет договора. {a_role} принимает на себя "
                     f"обязательство, предметом которого является {subject}.")
        lines.append(f"1.1. {b_role} обязуется принять и оплатить результат.")
    else:
        lines.append(f"1. Предмет договора. {a_role} обязуется обеспечить "
                     f"{subject}, а {b_role} — принять и оплатить результат.")

    price_text, stated_vat = money(rng, amount, vat)
    if rng.random() < 0.08:
        # цена не в тексте, а отсылкой к приложению
        lines.append("2. Цена договора определяется приложением № 1, "
                     "являющимся неотъемлемой частью настоящего договора.")
        truth["amount"] = None
    else:
        if hard and rng.random() < 0.45:
            alt = rng.choice([
                f"2. Стоимость работ по настоящему договору установлена "
                f"сторонами в размере {price_text}.",
                f"2. Общая сумма настоящего договора — {price_text}.",
                f"2. {b_role} оплачивает {a_role} {price_text} в порядке, "
                f"предусмотренном разделом 3.",
                f"2. Цена договора: {price_text}.",
            ])
            lines.append(alt)
        else:
            lines.append(f"2. Цена договора составляет {price_text}.")
        truth["vat"] = stated_vat
        if rng.random() < 0.05:
            # противоречие: в приложении другая сумма
            other = amount + rng.choice([100_000, 250_000, 500_000])
            other_text, _ = money(rng, other, vat)
            lines.append(f"2.1. Согласно приложению № 1 общая стоимость "
                         f"составляет {other_text}.")
            truth["contradiction"] = True

    if prepay:
        lines.append(f"3. {b_role} перечисляет аванс в размере {prepay}% "
                     f"от цены договора в течение 5 (пяти) рабочих дней.")
    else:
        lines.append(f"3. Оплата производится по факту в течение "
                     f"{rng.choice([10, 15, 20])} рабочих дней.")

    dw = num_words(days)
    spelled = f" ({dw})" if not dw.isdigit() else ""
    if hard and rng.random() < 0.3:
        d = rng.choice([50_000, 100_000, 250_000])
        lines.append(f"3.1. Обеспечительный платёж составляет "
                     f"{d:,} руб.".replace(",", " "))

    lines.append(f"4. Срок исполнения обязательств — {days}{spelled} "
                 f"календарных дней с даты подписания.")

    if "ставки" in penalty:
        lines.append(f"5. За нарушение сроков начисляется пеня в размере "
                     f"{penalty} за каждый день просрочки.")
    else:
        lines.append(f"5. За нарушение сроков начисляется неустойка "
                     f"{penalty}% от цены договора за каждый день просрочки.")

    # применимое право и суд: примерно в каждом седьмом договоре отсутствуют
    if rng.random() > 0.15:
        law = rng.choice(LAWS)
        truth["law"] = law
        if hard and rng.random() < 0.5:
            lines.append(rng.choice([
                f"6. Отношения сторон регулируются нормами, "
                f"составляющими {law}.",
                f"6. Настоящий договор подчинён {law}.",
            ]))
        else:
            lines.append(f"6. К отношениям сторон применяется {law}.")
    if rng.random() > 0.15:
        forum = rng.choice(FORUMS)
        truth["forum"] = forum
        if hard and rng.random() < 0.5:
            lines.append(rng.choice([
                f"7. Все разногласия подлежат рассмотрению в {forum}.",
                f"7. Компетентным судом стороны признают {forum}.",
            ]))
        else:
            lines.append(f"7. Споры передаются на разрешение в {forum}.")

    lines.append("8. Договор вступает в силу с момента подписания "
                 "уполномоченными представителями сторон.")

    text = "\n".join(lines)
    if rng.random() < (0.35 if hard else 0.2):
        text = ocr_noise(rng, text)
        truth["noisy"] = True
    else:
        truth["noisy"] = False

    return text, truth


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--contracts", type=int, default=600)
    ap.add_argument("--hard", action="store_true",
                    help="формулировки, под которые правила не писались, "
                         "и отвлекающие суммы в тексте")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/contracts.json")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    docs = []
    for i in range(args.contracts):
        text, truth = build(rng, i, args.hard)
        docs.append({"text": text, "truth": truth})

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False)

    t = [d["truth"] for d in docs]
    print(f"договоров: {len(docs)}")
    print(f"  без цены в тексте:      {sum(1 for x in t if x['amount'] is None)}")
    print(f"  с противоречием цены:   {sum(1 for x in t if x['contradiction'])}")
    print(f"  без применимого права:  {sum(1 for x in t if x['law'] is None)}")
    print(f"  без указания суда:      {sum(1 for x in t if x['forum'] is None)}")
    print(f"  со ставкой НДС в тексте:{sum(1 for x in t if x['vat'] is not None):>4}")
    print(f"  с шумом распознавания:  {sum(1 for x in t if x['noisy'])}")
    print(f"записано: {args.out}")


if __name__ == "__main__":
    main()
