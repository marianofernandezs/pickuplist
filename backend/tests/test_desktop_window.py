from threading import Event
from types import SimpleNamespace
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QKeySequence, QPalette
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QLabel
from app.desktop import application
from app.desktop.application import LocalSource, ProcessedBatch, SessionProduct
from app.desktop import main as desktop_main
from app.desktop.main import MainWindow, QFileDialog, QMessageBox
from app.services.document_summary import DocumentSummary
from app.services.extractor import ParsedProduct


def _extraction(name: str):
    return SimpleNamespace(
        page_count=1,
        requires_ocr=False,
        products=[ParsedProduct("SKU", name, 2, "CAJA", 1, "caja")],
        summary=DocumentSummary(name, "Contado"),
    )


def test_desktop_window_exposes_existing_filters_and_search(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.session.products.extend([
        SessionProduct("CAJA VERDE", "caja", 2, "caja"),
        SessionProduct("PACK AZUL", "pack", 3, "pack"),
        SessionProduct("LAPIZ", "unitario", 1, "un"),
    ])
    window.refresh_all()
    assert window.products.rowCount() == 3
    assert window.product_count.text() == "Productos · 3 resultados"
    window.filter.setCurrentIndex(window.filter.findData("pack"))
    assert window.products.rowCount() == 1
    assert window.product_count.text() == "Productos · 1 resultados"
    assert window.products.item(0, 1).text() == "PACK AZUL"
    window.filter.setCurrentIndex(window.filter.findData("all"))
    window.search.setText("lap")
    assert window.products.rowCount() == 1
    assert window.product_count.text() == "Productos · 1 resultados"
    assert window.products.item(0, 1).text() == "LAPIZ"
    assert window.search.isClearButtonEnabled()
    assert window.add_button.text() == "Cargar PDFs"
    assert window.reset_button.text() == "Limpiar sesión"


def test_close_without_worker_uses_owned_thread_attribute(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert window._worker_thread is None
    window.close()


def test_export_buttons_keep_their_targets_without_init_lambdas(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    calls = []
    monkeypatch.setattr(window, "export_pdf", lambda kind, name: calls.append((kind, name)))

    window.export_buttons[0].click()
    window.export_buttons[1].click()

    assert calls == [
        ("bodega", "Lista Pickeo Bodega.pdf"),
        ("local", "Lista Pickeo Local.pdf"),
    ]


def test_product_empty_state_distinguishes_initial_search_and_filter(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.products_stack.currentWidget() is window.products_empty
    assert window.products_empty.text() == "Agrega archivos PDF para comenzar"

    window.session.sources.append(LocalSource("items.pdf", 1, False, "processed"))
    window.session.products.append(SessionProduct("ARROZ", "caja", 4, "caja"))
    window.refresh_all()
    assert window.products_stack.currentWidget() is window.products
    window.search.setText("sin coincidencia")
    assert window.products_stack.currentWidget() is window.products_empty
    assert window.products_empty.text() == "No se encontraron productos con los filtros actuales"

    window.search.clear()
    window.filter.setCurrentIndex(window.filter.findData("pack"))
    assert window.products_empty.text() == "No se encontraron productos con los filtros actuales"
    window.close()


def test_no_products_state_guides_to_failed_source_details(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.session.sources.extend([
        LocalSource("failed.pdf", 0, False, "failed", "producto inválido"),
        LocalSource("empty.pdf", 1, False, "processed"),
    ])
    window.refresh_all()
    assert window.products_stack.currentWidget() is window.products_empty
    assert "No hay productos disponibles" in window.products_empty.text()
    assert "documentos con errores en Fuentes" in window.products_empty.text()

    window.session.sources = [LocalSource("empty.pdf", 1, False, "processed")]
    window.refresh_all()
    assert window.products_empty.text() == "Los documentos se procesaron, pero no hay productos disponibles."
    window.close()


def test_progress_label_reports_current_document_completion_and_cancellation(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._set_processing(True)
    window.progress.show()

    window.on_progress(2, 5)
    assert window.progress.value() == 2
    assert window.progress_label.text() == "Procesando documento 3 de 5"
    assert not window.reset_button.isEnabled()
    assert all(not button.isEnabled() for button in window.export_buttons)

    window.on_progress(5, 5)
    assert window.progress_label.text() == "Finalizando procesamiento…"

    window.on_processed(None, None)
    assert not window.progress.isVisible()
    assert window.progress_label.text() == "Procesamiento cancelado · no se añadieron resultados"
    assert window.session.products == []
    window._set_processing(False)
    assert window.reset_button.isEnabled()
    assert all(button.isEnabled() for button in window.export_buttons)
    window.close()


def test_source_detail_column_and_full_selected_error_are_accessible(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    long_error = 'Documento rechazado: producto "PRODUCTO EJEMPLO" tiene una cantidad inválida. ' * 12
    window.session.sources.append(LocalSource("failed.pdf", 2, True, "failed", long_error))
    window.refresh_all()

    assert window.sources.columnCount() == 5
    assert [window.sources.horizontalHeaderItem(i).text() for i in range(5)] == [
        "Archivo", "Estado", "Páginas", "Requiere OCR", "Detalle"
    ]
    assert window.sources.item(0, 0).text() == "failed.pdf"
    assert window.sources.item(0, 1).text() == "Fallido"
    assert window.sources.item(0, 2).text() == "2"
    assert window.sources.item(0, 3).text() == "Sí"
    assert window.sources.item(0, 4).text() == long_error
    assert window.sources.item(0, 4).toolTip() == long_error

    window.sources.setCurrentCell(0, 0)
    assert not window.source_detail.isHidden()
    assert window.source_detail.toPlainText() == long_error
    assert window.source_detail.isReadOnly()
    window.close()


def test_metric_cards_keep_session_totals_and_reflow_for_narrow_windows(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.session.sources.extend([
        LocalSource("one.pdf", 1, False, "processed"),
        LocalSource("two.pdf", 1, False, "processed"),
    ])
    window.session.products.extend([
        SessionProduct("CAJA A", "caja", 8, "caja"),
        SessionProduct("PACK B", "pack", 3, "pack"),
        SessionProduct("UNIT C", "unitario", 5, "un"),
    ])
    window.refresh_all()
    assert len(window._metric_cards) == 5
    assert {key: label.text() for key, label in window._metric_values.items()} == {
        "invoices": "2", "products": "3", "caja": "1", "pack": "1", "unitario": "1"
    }

    window.filter.setCurrentIndex(window.filter.findData("pack"))
    assert window.product_count.text() == "Productos · 1 resultados"
    assert window._metric_values["products"].text() == "3"

    window.show()
    window.resize(800, 600)
    qtbot.waitUntil(lambda: window._metric_columns == 5)
    assert window.width() == 800
    window.resize(760, 600)
    qtbot.waitUntil(lambda: window._metric_columns == 3)
    window.resize(1050, 720)
    qtbot.waitUntil(lambda: window._metric_columns == 5)
    window.close()


def test_product_table_alignment_sizing_and_splitter_configuration(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.session.products.append(SessionProduct("ARROZ LARGO", "caja", 12, "caja"))
    window.session.sources.append(LocalSource("failed.pdf", 2, True, "failed", "Error completo " * 20))
    window.refresh_all()

    assert window.products.columnWidth(0) == 130
    assert window.products.columnWidth(2) == 125
    assert window.products.horizontalHeader().sectionResizeMode(1).name == "Stretch"
    assert window.products.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert window.products.alternatingRowColors()
    assert window.products.verticalHeader().defaultSectionSize() == 30
    assert window.products.item(0, 0).textAlignment() & Qt.AlignmentFlag.AlignHCenter
    assert window.products.item(0, 1).textAlignment() & Qt.AlignmentFlag.AlignLeft
    assert window.products.item(0, 1).toolTip() == "ARROZ LARGO"
    assert window.products.item(0, 2).textAlignment() & Qt.AlignmentFlag.AlignRight

    assert window.splitter.orientation() == Qt.Orientation.Vertical
    assert window.splitter.count() == 2
    assert window.splitter.widget(0) is window.products_panel
    assert window.splitter.widget(1) is window.sources_panel
    assert window.products_panel.minimumHeight() >= 150
    assert window.sources_panel.minimumHeight() >= 100
    window.show()
    window.resize(800, 600)
    window.sources.setCurrentCell(0, 0)
    qtbot.waitUntil(lambda: sum(window.splitter.sizes()) > 0)
    upper, lower = window.splitter.sizes()
    assert upper > lower
    assert lower >= window.sources_panel.minimumSizeHint().height()
    assert window.source_detail.isVisible()
    assert all(button.isVisible() for button in window.export_buttons)
    assert window.sources.columnWidth(0) >= 240
    window.resize(1050, 720)
    qtbot.waitUntil(lambda: window.width() == 1050)
    window.showMaximized()
    qtbot.waitUntil(window.isMaximized)
    qtbot.waitUntil(lambda: sum(window.splitter.sizes()) > 0)
    assert min(window.splitter.sizes()) >= 100
    window.close()


def test_source_table_uses_compact_columns_localized_ocr_and_tooltips(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.session.sources.extend([
        LocalSource("DTE-76353833-8-33-111801.pdf", 1, False, "processed"),
        LocalSource("registro-interno-largo.pdf", 2, True, "failed", "Error completo"),
    ])
    window.refresh_all()
    assert window.sources.item(0, 3).text() == "No"
    assert window.sources.item(1, 3).text() == "Sí"
    assert window.sources.item(0, 0).toolTip() == "DTE-76353833-8-33-111801.pdf"
    assert window.sources.item(1, 4).toolTip() == "Error completo"
    assert window.sources.horizontalHeader().sectionResizeMode(4).name == "Stretch"
    assert window.export_buttons[0].text() == "Lista Pickeo Bodega"
    assert window.export_buttons[1].text() == "Lista Pickeo Local"
    assert all(button.isEnabled() for button in window.export_buttons)
    assert any(label.text() == "Productos CAJA y resumen de facturas." for label in window.exports_panel.findChildren(QLabel))
    assert any(label.text() == "Productos PACK y UNITARIO." for label in window.exports_panel.findChildren(QLabel))
    window._set_processing(True)
    assert all(not button.isEnabled() for button in window.export_buttons)
    window._set_processing(False)
    window.close()


def test_visual_refinements_use_system_palette_typography_and_native_states(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window._metric_cards[0].backgroundRole() == QPalette.ColorRole.AlternateBase
    assert window._metric_cards[0].autoFillBackground()
    assert window.products.palette().color(QPalette.ColorRole.Base) == window.palette().color(QPalette.ColorRole.Base)
    assert window.sources.palette().color(QPalette.ColorRole.Highlight) == window.palette().color(QPalette.ColorRole.Highlight)
    assert window.products.horizontalHeader().styleSheet() == ""
    assert window.sources.horizontalHeader().styleSheet() == ""
    assert window._metric_values["products"].font().pointSizeF() > window.font().pointSizeF()
    assert window._metric_values["products"].font().weight() == QFont.Weight.DemiBold
    assert window.search.minimumHeight() == window._control_height
    assert window.filter.minimumHeight() == window._control_height
    assert not window.reset_button.icon().isNull()
    assert all(not button.icon().isNull() for button in window.export_buttons)

    def contrast_ratio(first: QColor, second: QColor) -> float:
        def luminance(color: QColor) -> float:
            channels = [color.redF(), color.greenF(), color.blueF()]
            linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
                      for channel in channels]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        light, dark = sorted((luminance(first), luminance(second)), reverse=True)
        return (light + 0.05) / (dark + 0.05)

    for background, foreground in (("#ffffff", "#202124"), ("#292d32", "#f4f5f6")):
        palette = QPalette(window.palette())
        palette.setColor(QPalette.ColorRole.Button, QColor(background))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(foreground))
        window.setPalette(palette)
        for table in (window.products, window.sources):
            header_palette = table.horizontalHeader().palette()
            ratio = contrast_ratio(
                header_palette.color(QPalette.ColorRole.ButtonText),
                header_palette.color(QPalette.ColorRole.Button),
            )
            assert ratio >= 4.5
            assert table.horizontalHeader().font().weight() == QFont.Weight.DemiBold

    window.session.sources.append(LocalSource("failed.pdf", 1, False, "failed", "Error de lectura"))
    window.refresh_all()
    status_item = window.sources.item(0, 1)
    assert status_item.text() == "Fallido"
    assert not status_item.icon().isNull()
    assert status_item.font().weight() == QFont.Weight.DemiBold
    window.close()


def test_clearing_session_resets_cards_counter_filters_and_empty_state(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.session.sources.append(LocalSource("items.pdf", 1, False, "processed"))
    window.session.products.append(SessionProduct("PACK AZUL", "pack", 6, "pack"))
    window.refresh_all()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)

    window.reset_session()
    assert window._metric_values["invoices"].text() == "0"
    assert window._metric_values["products"].text() == "0"
    assert window.product_count.text() == "Productos · 0 resultados"
    assert window.products_stack.currentWidget() is window.products_empty
    assert window.products_empty.text() == "Agrega archivos PDF para comenzar"
    assert window.sources.rowCount() == 0
    window.close()


def test_accessible_names_platform_standard_shortcuts_and_tab_order(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.add_button.accessibleName() == "Cargar archivos PDF"
    assert window.search.accessibleName() == "Buscar productos por descripción"
    assert window.filter.accessibleName() == "Filtrar por presentación"
    assert window.products.accessibleName() == "Productos consolidados"
    assert window.sources.accessibleName() == "Documentos y fuentes"
    assert window.reset_button.isFlat()
    assert window.add_shortcut.key() == QKeySequence(QKeySequence.StandardKey.Open)
    assert window.find_shortcut.key() == QKeySequence(QKeySequence.StandardKey.Find)

    window.show()
    window.search.setFocus()
    qtbot.waitUntil(window.search.hasFocus)
    qtbot.keyClick(window.search, Qt.Key.Key_Tab)
    qtbot.waitUntil(window.filter.hasFocus)
    window.close()
    assert window._closing


def test_minimize_action_is_available_and_does_not_change_processing_or_session(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.session.products.append(SessionProduct("ARROZ", "caja", 4, "caja"))
    window._set_processing(True)
    window._cancel_event = Event()
    cancel_event = window._cancel_event

    window_menu = next(
        action.menu() for action in window.menuBar().actions()
        if action.menu() is not None and action.text() == "Ventana"
    )
    assert window_menu.actions() == [window.minimize_action]
    assert window.minimize_action.text() == "Minimizar"
    assert window.minimize_action.shortcut() == QKeySequence("Ctrl+M")

    window.minimize_action.trigger()
    qtbot.waitUntil(window.isMinimized)

    assert window._processing
    assert not cancel_event.is_set()
    assert not window._closing
    assert [product.description_exact for product in window.session.products] == ["ARROZ"]
    assert not window.reset_button.isEnabled()
    assert all(not button.isEnabled() for button in window.export_buttons)
    window._set_processing(False)
    window._cancel_event = None
    window.close()


def test_single_pdf_is_committed_once_and_controls_are_restored(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: (["sample.pdf"], ""))
    monkeypatch.setattr(application, "extract_pdf", lambda path: _extraction("SAMPLE"))
    window.choose_files()
    qtbot.waitUntil(lambda: window._worker_thread is None, timeout=5000)
    assert window._worker is None
    assert window.add_button.isEnabled()
    assert window.reset_button.isEnabled()
    assert all(button.isEnabled() for button in window.export_buttons)
    assert len(window.session.sources) == 1
    assert len(window.session.products) == 1
    assert len(window.session.summaries) == 1
    assert window.session.sources[0].filename == "sample.pdf"
    assert window.session.products[0].description_exact == "SAMPLE"
    window.close()


def test_multiple_pdfs_are_published_as_one_batch(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: (["one.pdf", "two.pdf"], ""))
    monkeypatch.setattr(application, "extract_pdf", lambda path: _extraction(str(path)))
    window.choose_files()
    qtbot.waitUntil(lambda: window._worker_thread is None, timeout=5000)
    assert [source.filename for source in window.session.sources] == ["one.pdf", "two.pdf"]
    assert [product.description_exact for product in window.session.products] == ["one.pdf", "two.pdf"]
    assert len(window.session.summaries) == 2
    assert len({product.description_exact for product in window.session.products}) == 2
    window.close()


def test_reset_and_export_are_blocked_until_batch_finishes(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.session.sources.append(LocalSource("existing.pdf", 1, False, "processed"))
    window.session.products.append(SessionProduct("EXISTING", "caja", 1, "caja"))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: (["sample.pdf"], ""))
    started, release = Event(), Event()

    def extract(path):
        started.set()
        release.wait(timeout=3)
        return _extraction("NEW")

    monkeypatch.setattr(application, "extract_pdf", extract)
    save_dialog_calls = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (save_dialog_calls.append(True), ("", ""))[1])
    window.choose_files()
    qtbot.waitUntil(started.is_set, timeout=2000)
    assert not window.add_button.isEnabled()
    assert not window.reset_button.isEnabled()
    assert all(not button.isEnabled() for button in window.export_buttons)

    # Also guard the action slots against programmatic invocation while busy.
    window.reset_session()
    window.export_pdf("bodega", "out.pdf")
    assert len(window.session.sources) == 1
    assert [product.description_exact for product in window.session.products] == ["EXISTING"]
    assert save_dialog_calls == []

    release.set()
    qtbot.waitUntil(lambda: window._worker_thread is None, timeout=5000)
    assert [source.filename for source in window.session.sources] == ["existing.pdf", "sample.pdf"]
    assert [product.description_exact for product in window.session.products] == ["EXISTING", "NEW"]
    assert len(window.session.products) == 2  # No partial or duplicate commit.
    assert window.add_button.isEnabled()
    assert window.reset_button.isEnabled()
    assert all(button.isEnabled() for button in window.export_buttons)
    window.close()


def test_extraction_error_is_recorded_without_partial_products(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: (["bad.pdf"], ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)

    def extract(_path):
        raise ValueError("document cannot be read")

    monkeypatch.setattr(application, "extract_pdf", extract)
    window.choose_files()
    qtbot.waitUntil(lambda: window._worker_thread is None, timeout=5000)
    assert len(window.session.sources) == 1
    assert window.session.sources[0].status == "failed"
    assert "document cannot be read" in window.session.sources[0].error
    assert window.session.products == []
    assert window.session.summaries == []
    assert window.add_button.isEnabled()
    assert window.reset_button.isEnabled()
    assert all(button.isEnabled() for button in window.export_buttons)
    window.close()


def test_batch_error_does_not_publish_partial_results_and_restores_controls(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.session.sources.append(LocalSource("existing.pdf", 1, False, "processed"))
    window.session.products.append(SessionProduct("EXISTING", "caja", 1, "caja"))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: (["sample.pdf"], ""))
    monkeypatch.setattr(desktop_main, "process_files", lambda *args: (_ for _ in ()).throw(RuntimeError("batch failed")))
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    window.choose_files()
    qtbot.waitUntil(lambda: window._worker_thread is None, timeout=5000)
    assert [source.filename for source in window.session.sources] == ["existing.pdf"]
    assert [product.description_exact for product in window.session.products] == ["EXISTING"]
    assert window.add_button.isEnabled()
    assert window.reset_button.isEnabled()
    assert all(button.isEnabled() for button in window.export_buttons)
    window.close()


def test_close_during_pdf_cancels_and_discards_pending_result(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: (["sample.pdf"], ""))
    started, release = Event(), Event()

    def process_batch(paths, progress=None, cancel_event=None):
        started.set()
        release.wait()
        # Simulate a completed result that was queued just as close was requested.
        return ProcessedBatch(
            (LocalSource("sample.pdf", 1, False, "processed"),),
            (SessionProduct("LATE", "caja", 1, "caja"),),
            (DocumentSummary("1", "Contado"),),
        )

    monkeypatch.setattr(desktop_main, "process_files", process_batch)
    window.choose_files()
    qtbot.waitUntil(started.is_set, timeout=2000)
    thread = window._worker_thread
    thread_finished = Event()
    thread.finished.connect(thread_finished.set)
    cancel_event = window._cancel_event
    window.close()
    assert window._closing
    assert cancel_event is not None and cancel_event.is_set()
    assert thread is not None and thread.isRunning()
    assert window.session.sources == []
    assert window.session.products == []

    # Repeated close requests are idempotent while the active extraction winds down.
    window.close()
    release.set()
    qtbot.waitUntil(lambda: window._worker_thread is None, timeout=5000)
    assert thread_finished.is_set()
    assert window.session.sources == []
    assert window.session.products == []
    assert window.session.summaries == []
    assert not window.add_button.isEnabled()


def test_close_during_batch_stops_before_next_pdf_and_preserves_prior_session(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.session.add_batch(ProcessedBatch(
        (LocalSource("prior.pdf", 1, False, "processed"),),
        (SessionProduct("PRIOR", "caja", 4, "caja"),),
        (DocumentSummary("prior", "Contado"),),
    ))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: (["one.pdf", "two.pdf"], ""))
    started, release = Event(), Event()
    extracted = []

    def extract(path):
        extracted.append(str(path))
        if path.name == "one.pdf":
            started.set()
            release.wait()
        return _extraction(path.name)

    monkeypatch.setattr(application, "extract_pdf", extract)
    window.choose_files()
    qtbot.waitUntil(started.is_set, timeout=2000)
    thread = window._worker_thread
    thread_finished = Event()
    thread.finished.connect(thread_finished.set)
    window.close()
    assert window._cancel_event is not None and window._cancel_event.is_set()
    release.set()
    qtbot.waitUntil(lambda: window._worker_thread is None, timeout=5000)

    assert thread_finished.is_set()
    assert extracted == ["one.pdf"]
    assert [source.filename for source in window.session.sources] == ["prior.pdf"]
    assert [product.description_exact for product in window.session.products] == ["PRIOR"]
    assert len(window.session.summaries) == 1


def test_application_cancellation_is_checked_between_documents(monkeypatch) -> None:
    cancel = Event()
    extracted = []

    def extract(path):
        extracted.append(Path(path).name)
        return _extraction(Path(path).name)

    monkeypatch.setattr(application, "extract_pdf", extract)

    def request_cancel_after_first(completed, total):
        assert total == 3
        if completed == 1:
            cancel.set()

    result = application.process_files(
        ["one.pdf", "two.pdf", "three.pdf"],
        progress=request_cancel_after_first,
        cancel_event=cancel,
    )
    assert result is None
    assert extracted == ["one.pdf"]


def test_close_after_completion_is_safe_and_leaves_no_running_thread(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: (["sample.pdf"], ""))
    monkeypatch.setattr(application, "extract_pdf", lambda path: _extraction("SAMPLE"))
    window.choose_files()
    qtbot.waitUntil(lambda: window._worker_thread is None, timeout=5000)
    assert len(window.session.products) == 1
    window.close()
    window.close()
    assert window._closing
    assert window._worker_thread is None
