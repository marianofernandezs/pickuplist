from app.services.registro_interno_parser import parseRegistroInternoBuffer


def test_parse_registro_interno_buffer_critical_product() -> None:
    parsed = parseRegistroInternoBuffer(
        "BODEGAAS54 ALCOHOL SPRAY ECOSAFE 5 LTS X 4 BIDONES 1 CAJA $48.924 SI $48.924"
    )

    assert parsed == {
        "sku": "BODEGAAS54",
        "descripcion_exacta": "ALCOHOL SPRAY ECOSAFE 5 LTS X 4 BIDONES",
        "cantidad": 1,
        "tipo_presentacion": "CAJA",
    }


def test_parse_registro_interno_buffer_ignores_everything_after_quantity() -> None:
    parsed = parseRegistroInternoBuffer(
        "BODEGAAS54 ALCOHOL SPRAY ECOSAFE 5 LTS X 4 BIDONES 1 CAJA $48.924 SI $48.924"
    )

    assert parsed is not None
    assert parsed["descripcion_exacta"] == "ALCOHOL SPRAY ECOSAFE 5 LTS X 4 BIDONES"
