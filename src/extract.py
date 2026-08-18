"""
Извлечение структурированных данных из договоров.

Две ветки. Основная — правила и регулярные выражения, работает без сети и
без ключей. Дополнительная — языковая модель, включается переменной
окружения LLM_API_KEY; без неё просто не запускается, чтобы репозиторий был
воспроизводим у любого.

Правила писались под общий вид формулировок, а не под конкретные шаблоны
генератора. Это принципиально: правила, подогнанные под генератор, дадут
точность около единицы и не покажут ничего.

Отдельно считаются проверки на самосогласованность — сумма прописью против
суммы цифрами, срок цифрами против срока прописью, цена в тексте против
цены в приложении. Расхождение здесь не ошибка извлечения, а находка:
именно так обнаруживаются противоречия внутри договора.
"""

import os
import re

NBSP = "\u00a0"

# ---------------------------------------------------------------------------
# Нормализация
# ---------------------------------------------------------------------------


def unwrap(text):
    """Снять переносы внутри слов и привести пробелы к обычным."""
    text = text.replace("-\n", "")
    return text.replace(NBSP, " ").replace("\u2009", " ")


def to_number(s):
    """«1 000 000,00» и «1 000 000» в int. Копейки отбрасываются."""
    s = s.replace(NBSP, " ").replace(" ", "")
    s = re.sub(r",\d{1,2}$", "", s)
    s = s.replace(",", "")
    return int(s) if s.isdigit() else None


WORD_NUM = {
    "один": 1, "два": 2, "три": 3, "четыре": 4, "пять": 5,
    "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
}


def words_to_number(s):
    """Разбор простых форм вида «два миллиона», «45 тысяч»."""
    s = s.lower().strip()
    m = re.match(r"(\d+)\s*тысяч", s)
    if m:
        return int(m.group(1)) * 1000
    for w, v in WORD_NUM.items():
        if s.startswith(w) and "миллион" in s:
            return v * 1_000_000
    return None


# ---------------------------------------------------------------------------
# Правила извлечения
# ---------------------------------------------------------------------------

RE_PARTY = re.compile(
    r"(ООО|АО|ПАО|ИП)\s*«([^»]+)»\s*\(ИНН\s*(\d{9,12})\)", re.I)

RE_SUBJECT = re.compile(
    r"[Пп]редмет договора\.?\s*[^.]*?обязуется\s+обеспечить\s+(.+?),\s*а\s",
    re.S)

RE_AMOUNT_MLN = re.compile(
    r"(?:цена|стоимость)[^.]{0,40}?составляет\s+([\d,]+)\s*(млн|тыс)\.?",
    re.I | re.S)

RE_AMOUNT = re.compile(
    r"[Цц]ена договора составляет\s+([\d\s\u00a0,]+)", re.S)

RE_AMOUNT_ANY = re.compile(
    r"(?:стоимость|цена)[^.]{0,40}?составляет\s+([\d\s\u00a0,]+)", re.I | re.S)

RE_APPENDIX_PRICE = re.compile(
    r"приложени[юя][^.]{0,60}?(?:стоимость|цена)[^.]{0,40}?"
    r"составляет\s+([\d\s\u00a0,]+)", re.I | re.S)

RE_WORDS_IN_BRACKETS = re.compile(r"\(([^)]*(?:миллион|тысяч)[^)]*)\)")

RE_VAT = re.compile(r"НДС\s*(\d{1,2})\s*%", re.I)
RE_NO_VAT = re.compile(r"НДС\s+не\s+облагается", re.I)

RE_PREPAY = re.compile(r"аванс[^.]{0,40}?(\d{1,2})\s*%", re.I | re.S)

RE_PENALTY_PCT = re.compile(
    r"неустойка\s+([\d,]+)\s*%[^.]{0,60}?за каждый день", re.I | re.S)
RE_PENALTY_RATE = re.compile(
    r"пеня[^.]{0,40}?(1/\d{2,3}\s+ключевой ставки)", re.I | re.S)

RE_TERM = re.compile(
    r"[Сс]рок[^.]{0,60}?—\s*(\d+)\s*\(", re.S)
RE_TERM_ANY = re.compile(r"(\d+)\s*календарных дней", re.I)

RE_LAW = re.compile(
    r"применяется\s+(.+?)\.", re.I | re.S)
RE_FORUM = re.compile(
    r"[Сс]поры[^.]{0,60}?в\s+(.+?)\.", re.S)


def extract(text):
    """Вернуть словарь полей. Отсутствующее поле — None, а не догадка."""
    t = unwrap(text)
    out = {k: None for k in ("party_a", "inn_a", "party_b", "inn_b",
                             "subject", "amount", "vat", "prepay_percent",
                             "penalty", "term_days", "law", "forum")}
    flags = {"amount_words_mismatch": False, "term_words_mismatch": False,
             "price_contradiction": False}

    parties = RE_PARTY.findall(t)
    if len(parties) >= 2:
        out["party_a"] = f'{parties[0][0].upper()} «{parties[0][1]}»'
        out["inn_a"] = parties[0][2]
        out["party_b"] = f'{parties[1][0].upper()} «{parties[1][1]}»'
        out["inn_b"] = parties[1][2]

    m = RE_SUBJECT.search(t)
    if m:
        out["subject"] = " ".join(m.group(1).split())

    # сокращения разбираются первыми: «7 млн руб.» иначе прочтётся как 7
    m = RE_AMOUNT_MLN.search(t)
    if m:
        base = to_number(m.group(1))
        if base is not None:
            out["amount"] = base * (1_000_000 if m.group(2).lower() == "млн"
                                    else 1000)
    else:
        m = RE_AMOUNT.search(t) or RE_AMOUNT_ANY.search(t)
        if m:
            out["amount"] = to_number(m.group(1))

    # сумма прописью в скобках — проверка на самосогласованность
    w = RE_WORDS_IN_BRACKETS.search(t)
    if w and out["amount"]:
        spelled = words_to_number(w.group(1))
        if spelled and spelled != out["amount"]:
            flags["amount_words_mismatch"] = True

    # цена в приложении против цены в тексте
    ap = RE_APPENDIX_PRICE.search(t)
    if ap and out["amount"]:
        other = to_number(ap.group(1))
        if other and other != out["amount"]:
            flags["price_contradiction"] = True

    if RE_NO_VAT.search(t):
        out["vat"] = 0
    else:
        m = RE_VAT.search(t)
        if m:
            out["vat"] = int(m.group(1))

    m = RE_PREPAY.search(t)
    out["prepay_percent"] = int(m.group(1)) if m else 0

    m = RE_PENALTY_RATE.search(t)
    if m:
        out["penalty"] = " ".join(m.group(1).split())
    else:
        m = RE_PENALTY_PCT.search(t)
        if m:
            out["penalty"] = m.group(1)

    m = RE_TERM.search(t) or RE_TERM_ANY.search(t)
    if m:
        out["term_days"] = int(m.group(1))

    m = RE_LAW.search(t)
    if m:
        out["law"] = " ".join(m.group(1).split())

    m = RE_FORUM.search(t)
    if m:
        out["forum"] = " ".join(m.group(1).split())

    return out, flags


# ---------------------------------------------------------------------------
# Ветка с языковой моделью
# ---------------------------------------------------------------------------

def extract_llm(text):
    """
    Заглушка для второй ветки. Включается наличием LLM_API_KEY.
    В измерениях репозитория не участвует: ключа нет, и придумывать
    метрики для неизмеренной ветки нельзя.
    """
    if not os.environ.get("LLM_API_KEY"):
        raise RuntimeError(
            "Ветка с языковой моделью требует переменной окружения "
            "LLM_API_KEY. Без неё используйте извлечение по правилам.")
    raise NotImplementedError(
        "Реализация запроса к модели не входит в измеряемую часть "
        "репозитория. Схема полей описана в extract(); передайте её "
        "модели как JSON Schema и сверьте результат теми же метриками.")
