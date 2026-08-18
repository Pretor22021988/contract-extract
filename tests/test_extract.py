import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extract import (extract, to_number, unwrap, words_to_number)

CONTRACT = """ДОГОВОР № 101/24
г. Москва
ООО «Вектор» (ИНН 7701234567), именуемое в дальнейшем «Подрядчик», и АО «Гранит» (ИНН 7809876543), именуемое в дальнейшем «Заказчик», заключили настоящий договор о нижеследующем.
1. Предмет договора. Подрядчик обязуется обеспечить выполнение ремонтных работ на объекте, а Заказчик — принять и оплатить результат.
2. Цена договора составляет 1 000 000,00 руб., в том числе НДС 20%.
3. Заказчик перечисляет аванс в размере 30% от цены договора в течение 5 (пяти) рабочих дней.
4. Срок исполнения обязательств — 90 календарных дней с даты подписания.
5. За нарушение сроков начисляется неустойка 0,1% от цены договора за каждый день просрочки.
6. К отношениям сторон применяется право Российской Федерации.
7. Споры передаются на разрешение в Арбитражный суд города Москвы.
"""

BARE = """ДОГОВОР № 5/24
ООО «Астра» (ИНН 7700000001), именуемое «Исполнитель», и ООО «Сфера» (ИНН 7700000002), именуемое «Заказчик», заключили договор.
2. Цена договора составляет 500 000 руб.
"""


def test_to_number_handles_spaces_and_kopecks():
    assert to_number("1 000 000") == 1_000_000
    assert to_number("1\u00a0250\u00a0000") == 1_250_000
    assert to_number("750 000,00") == 750_000


def test_to_number_rejects_garbage():
    assert to_number("не число") is None


def test_words_to_number():
    assert words_to_number("два миллиона") == 2_000_000
    assert words_to_number("45 тысяч") == 45_000
    assert words_to_number("что-то") is None


def test_unwrap_joins_hyphenated_words():
    assert "договор" in unwrap("дого-\nвор")


def test_extract_parties_and_inn():
    got, _ = extract(CONTRACT)
    assert got["party_a"] == 'ООО «Вектор»'
    assert got["inn_a"] == "7701234567"
    assert got["party_b"] == 'АО «Гранит»'


def test_extract_amount_and_vat():
    got, _ = extract(CONTRACT)
    assert got["amount"] == 1_000_000
    assert got["vat"] == 20


def test_extract_abbreviated_amount():
    got, _ = extract("2. Цена договора составляет 7 млн руб.")
    assert got["amount"] == 7_000_000


def test_extract_terms():
    got, _ = extract(CONTRACT)
    assert got["prepay_percent"] == 30
    assert got["term_days"] == 90
    assert got["penalty"] == "0,1"


def test_extract_law_and_forum():
    got, _ = extract(CONTRACT)
    assert "Российской Федерации" in got["law"]
    assert "Арбитражный суд города Москвы" in got["forum"]


def test_absent_fields_stay_empty():
    """Главное свойство: чего нет в тексте, того нет и в выдаче."""
    got, _ = extract(BARE)
    assert got["law"] is None
    assert got["forum"] is None
    assert got["term_days"] is None


def test_no_vat_clause():
    got, _ = extract("2. Цена договора составляет 500 000 рублей, НДС не облагается.")
    assert got["vat"] == 0


def test_price_contradiction_detected():
    text = ("2. Цена договора составляет 1 000 000 руб.\n"
            "2.1. Согласно приложению № 1 общая стоимость составляет 1 500 000 руб.")
    _, flags = extract(text)
    assert flags["price_contradiction"] is True


def test_no_contradiction_when_amounts_agree():
    text = ("2. Цена договора составляет 1 000 000 руб.\n"
            "2.1. Согласно приложению № 1 общая стоимость составляет 1 000 000 руб.")
    _, flags = extract(text)
    assert flags["price_contradiction"] is False
