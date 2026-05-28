from app.services.extractor import _parse_collapsed_glosa_cell


def test_bolsa_transparente_quantity_is_caja_not_unds() -> None:
    row = "BOLSA BASURA TRANSPARENTE 90X110 CM X 2 CAJA $24.495,80 SI $48.992 100 UNDS"
    parsed = _parse_collapsed_glosa_cell(row)
    assert parsed is not None
    glosa, cantidad = parsed
    assert glosa == "BOLSA BASURA TRANSPARENTE 90X110 CM X 100 UNDS"
    assert cantidad == "2 CAJA"


def test_servilleta_quantity_is_caja_not_paq() -> None:
    row = "SERVILLETA ELITE INTERFOLIADA DH 400 UNDS 2 CAJA $29.714,29 SI $59.429 X 18 PAQ"
    parsed = _parse_collapsed_glosa_cell(row)
    assert parsed is not None
    glosa, cantidad = parsed
    assert glosa == "SERVILLETA ELITE INTERFOLIADA DH 400 UNDS X 18 PAQ"
    assert cantidad == "2 CAJA"


def test_jabon_bidones_multiline_style() -> None:
    row = "JABON LIQUIDO MANZANA MR ROB 5 LTS X 4 2 CAJA $21.865,55 SI $43.731 BIDONES"
    parsed = _parse_collapsed_glosa_cell(row)
    assert parsed is not None
    glosa, cantidad = parsed
    assert glosa == "JABON LIQUIDO MANZANA MR ROB 5 LTS X 4 BIDONES"
    assert cantidad == "2 CAJA"
