from gresb_diff.models import FieldRecord, Difference, parse_value


def test_parse_value_decimal():
    assert parse_value(" 113.94 ") == ("113.94", 113.94)


def test_parse_value_integer():
    assert parse_value("28") == ("28", 28.0)


def test_parse_value_with_commas_and_percent():
    assert parse_value("3,919,797") == ("3,919,797", 3919797.0)
    assert parse_value("41.65%") == ("41.65%", 41.65)


def test_parse_value_non_numeric():
    assert parse_value("Energy Star Portfolio Manager") == (
        "Energy Star Portfolio Manager",
        None,
    )


def test_parse_value_blank():
    assert parse_value("") == ("", None)
    assert parse_value("-") == ("-", None)
    assert parse_value("N/A") == ("N/A", None)


def test_field_record_is_hashable_and_frozen():
    r = FieldRecord("Energy", "EN1", "Hotel | United States",
                    "Whole Site: Indirect Fuel",
                    "Absolute | Reporting Year Usage (MWh)",
                    "1046.8", 1046.8, "docx")
    assert r.value_num == 1046.8
    assert {r}  # hashable


def test_difference_fields():
    d = Difference("Energy", "Hotel | United States", "en.x",
                   "pdf name", "1.0", "docx name", "2.0", "value_mismatch")
    assert d.status == "value_mismatch"
