from pathlib import Path

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.desktop.application import PickListSession, process_files
from app.models.entities import ProductCandidate, SourceFile
from app.services.classifier import parse_quantity_cell
from app.services.extractor import _parsed_registry_product, extract_pdf, parse_pdf
from app.services.pdf_exporter import export_vige_pdf
from app.services.registro_interno_parser import parseRegistroInternoBuffer

EXPECTED = [
    ('LOCALCHCA', 'CUCHARA HELADO COLORES ACRILICA X 1000 UNDS', 1, 'PACK'),
    ('LOCALE161', 'ESTUCHE PET 161', 100, 'UNITARIO'),
    ('LOCALPB4012', 'POTE BISAGRA 40-12 FL', 50, 'UNITARIO'),
    ('LOCALPB408', 'POTE BISAGRA 40-8 FL', 50, 'UNITARIO'),
]
REAL_DIR = Path('/Users/mariano/Downloads/Facturas Piqueo 2')


def pdf_text(path):
    with fitz.open(path) as pdf:
        return ' '.join(page.get_text() for page in pdf)


def registry_pdf(path, rows):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 40), 'REGISTRO INTERNO DISMINUYE STOCK')
    for index, row in enumerate(rows):
        page.insert_text((40, 65 + index * 22), row, fontsize=9)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture(params=['representativo', 'original'])
def registry_1662(request, tmp_path):
    if request.param == 'original':
        path = REAL_DIR / 'Registro_interno_disminuye_stock_1662.pdf'
        if not path.is_file():
            pytest.skip('PDF original 1662 no disponible')
        return path
    rows = [f'{sku} {desc} {qty} {"UN" if presentation == "UNITARIO" else presentation} $100 SI $100'
            for sku, desc, qty, presentation in EXPECTED]
    return registry_pdf(tmp_path / '1662.pdf', rows)


@pytest.fixture(params=['representativo', 'original'])
def registry_1663(request, tmp_path):
    if request.param == 'original':
        path = REAL_DIR / 'Registro_interno_disminuye_stock_1663.pdf'
        if not path.is_file():
            pytest.skip('PDF original 1663 no disponible')
        return path
    return registry_pdf(tmp_path / '1663.pdf',
                        [f'BODEGA{i:03} PRODUCTO {i:03} 1 CAJA $100 SI $100' for i in range(21)])


def make_session(path):
    batch = process_files([path])
    assert batch is not None and batch.sources[0].status == 'processed'
    session = PickListSession.empty()
    session.add_batch(batch)
    return session


def test_1662_extraction_persistence_and_local_export(registry_1662, tmp_path):
    result = extract_pdf(registry_1662)
    assert [(p.sku, p.descripcion_exacta, p.cantidad, p.tipo_presentacion) for p in result.products] == EXPECTED
    session = make_session(registry_1662)
    text = pdf_text(session.export(tmp_path / 'local.pdf', 'local'))
    for _, description, quantity, presentation in EXPECTED:
        assert description in text
        assert f'{"UNIDAD" if presentation == "UNITARIO" else presentation} {quantity}' in text

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source = SourceFile(filename=registry_1662.name, stored_path=str(registry_1662))
        db.add(source)
        db.commit()
        parse_pdf(db, source)
        candidates = db.query(ProductCandidate).all()
        assert [(p.sku, p.presentation, p.quantity) for p in candidates] == [
            (sku, presentation.lower(), quantity) for sku, _, quantity, presentation in EXPECTED
        ]
        web_text = pdf_text(export_vige_pdf(db, tmp_path / 'web.pdf', allowed_presentations=('unitario', 'pack')))
        assert all(description in web_text for _, description, _, _ in EXPECTED)


def test_1663_exclusively_exports_21_boxes(registry_1663, tmp_path):
    products = extract_pdf(registry_1663).products
    assert len(products) == 21
    assert all(p.tipo_presentacion == 'CAJA' for p in products)
    assert len({(p.sku, p.descripcion_exacta, p.cantidad) for p in products}) == 21
    session = make_session(registry_1663)
    bodega = pdf_text(session.export(tmp_path / 'bodega.pdf', 'bodega'))
    local = pdf_text(session.export(tmp_path / 'local.pdf', 'local'))
    for product in products:
        assert product.descripcion_exacta in bodega
        assert product.descripcion_exacta not in local


def test_registry_paq_and_invoice_quantity_vocabulary():
    parsed = parseRegistroInternoBuffer('BODEGA123 PRODUCTO 2 PAQ $100 SI $200')
    assert parsed and parsed['tipo_presentacion'] == 'PAQ'
    product = _parsed_registry_product(parsed, 1)
    assert (product.tipo_presentacion, product.cantidad, product.unit) == ('PACK', 2, 'pack')
    assert [(parse_quantity_cell(value).presentation, parse_quantity_cell(value).quantity)
            for value in ('2 PACK', '3 PAQ', '4 CAJA', '5 UN')] == [
                ('pack', 2), ('pack', 3), ('caja', 4), ('unitario', 5)]
