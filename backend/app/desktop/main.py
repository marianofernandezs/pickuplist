from __future__ import annotations

import sys
import tempfile
import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Event, get_ident

from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtGui import (QAction, QFont, QKeySequence, QPalette, QShortcut, QIcon,
                           QPainter, QPageLayout, QPageRanges)
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPushButton, QComboBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget, QProgressBar,
                               QHeaderView, QStackedWidget, QPlainTextEdit, QStyle, QSplitter,
                               QSizePolicy)

from app.desktop.application import PickListSession, ProcessedBatch, process_files


logger = logging.getLogger(__name__)


def _log_print_pdf_state(stage: str, path: Path) -> None:
    """Log print-PDF metadata without exposing document contents."""
    try:
        absolute_path = path.resolve(strict=False)
        stat = absolute_path.stat()
        logger.debug(
            "Print PDF %s: path=%s exists=true size_bytes=%d thread_id=%s",
            stage,
            absolute_path,
            stat.st_size,
            get_ident(),
        )
    except OSError:
        logger.debug(
            "Print PDF %s: path=%s exists=false size_bytes=0 thread_id=%s",
            stage,
            path.resolve(strict=False),
            get_ident(),
        )


def _cleanup_print_temp_directory(directory: tempfile.TemporaryDirectory) -> None:
    path = Path(directory.name)
    logger.debug(
        "Removing print temporary directory: path=%s thread_id=%s",
        path.resolve(strict=False),
        get_ident(),
    )
    directory.cleanup()
    logger.debug(
        "Removed print temporary directory: path=%s exists=%s thread_id=%s",
        path.resolve(strict=False),
        path.exists(),
        get_ident(),
    )


def resource_path(relative_path: str) -> Path:
    """Resolve a bundled desktop resource in source and frozen applications."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / relative_path


class ProcessWorker(QObject):
    finished = Signal(object, object)
    progress = Signal(int, int)

    def __init__(self, paths: list[str], cancel_event: Event):
        super().__init__()
        self.paths = paths
        self.cancel_event = cancel_event

    def run(self):
        try:
            batch = process_files(self.paths, self.progress.emit, self.cancel_event)
            self.finished.emit(batch, None)
        except Exception as exc:
            self.finished.emit(None, str(exc))


class PrintPdfWorker(QObject):
    finished = Signal(object, object, object)

    def __init__(self, session: PickListSession, kind: str):
        super().__init__()
        self.session = session
        self.kind = kind

    def run(self):
        temporary_directory = None
        try:
            temporary_directory = tempfile.TemporaryDirectory(prefix="pick-list-print-")
            path = Path(temporary_directory.name) / f"{self.kind}.pdf"
            logger.debug(
                "Print PDF export starting: path=%s thread_id=%s",
                path.resolve(strict=False),
                get_ident(),
            )
            exported_path = self.session.export(path, self.kind)
            path = Path(exported_path).resolve(strict=True)
            _log_print_pdf_state("after export completed", path)
            self.finished.emit(str(path), None, temporary_directory)
        except Exception as exc:
            if temporary_directory is not None:
                _cleanup_print_temp_directory(temporary_directory)
            self.finished.emit(None, str(exc), None)


@dataclass(frozen=True)
class PrinterSettings:
    """Copy dialog choices as value data; never pass QPrinter across threads."""

    printer_name: str
    page_layout: QPageLayout
    resolution: int
    color_mode: QPrinter.ColorMode
    duplex: QPrinter.DuplexMode
    copy_count: int
    collate_copies: bool
    page_order: QPrinter.PageOrder
    print_range: QPrinter.PrintRange
    from_page: int
    to_page: int
    page_ranges: QPageRanges
    paper_source: QPrinter.PaperSource
    full_page: bool
    output_format: QPrinter.OutputFormat
    output_file_name: str
    font_embedding_enabled: bool

    @classmethod
    def from_printer(cls, printer: QPrinter) -> "PrinterSettings":
        return cls(
            printer_name=printer.printerName(),
            page_layout=QPageLayout(printer.pageLayout()),
            resolution=printer.resolution(),
            color_mode=printer.colorMode(),
            duplex=printer.duplex(),
            copy_count=printer.copyCount(),
            collate_copies=printer.collateCopies(),
            page_order=printer.pageOrder(),
            print_range=printer.printRange(),
            from_page=printer.fromPage(),
            to_page=printer.toPage(),
            page_ranges=QPageRanges(printer.pageRanges()),
            paper_source=printer.paperSource(),
            full_page=printer.fullPage(),
            output_format=printer.outputFormat(),
            output_file_name=printer.outputFileName(),
            font_embedding_enabled=printer.fontEmbeddingEnabled(),
        )

    def apply_to(self, printer: QPrinter) -> None:
        if self.printer_name:
            printer.setPrinterName(self.printer_name)
        printer.setPageLayout(self.page_layout)
        printer.setResolution(self.resolution)
        printer.setColorMode(self.color_mode)
        printer.setDuplex(self.duplex)
        printer.setCopyCount(self.copy_count)
        printer.setCollateCopies(self.collate_copies)
        printer.setPageOrder(self.page_order)
        printer.setPrintRange(self.print_range)
        printer.setFromTo(self.from_page, self.to_page)
        printer.setPageRanges(self.page_ranges)
        printer.setPaperSource(self.paper_source)
        printer.setFullPage(self.full_page)
        printer.setOutputFormat(self.output_format)
        printer.setOutputFileName(self.output_file_name)
        printer.setFontEmbeddingEnabled(self.font_embedding_enabled)


class PrintSendWorker(QObject):
    finished = Signal(bool, object)

    def __init__(self, path: Path, settings: PrinterSettings):
        super().__init__()
        self.path = path
        self.settings = settings

    def run(self) -> None:
        document = None
        printer = None
        painter = None
        painter_started = False
        error = None
        accepted = False
        try:
            # These Qt paint/PDF objects are created and destroyed in this worker
            # thread. Only immutable/value settings cross from the UI thread.
            document = QPdfDocument()
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            painter = QPainter()
            self.settings.apply_to(printer)
            if not printer.isValid():
                raise RuntimeError("La impresora seleccionada ya no está disponible.")
            absolute_path = self.path.resolve(strict=False)
            _log_print_pdf_state("immediately before QPdfDocument.load", absolute_path)
            load_error = document.load(str(absolute_path))
            if load_error != QPdfDocument.Error.None_ or document.status() != QPdfDocument.Status.Ready:
                raise RuntimeError(f"No se pudo cargar el PDF para imprimir (error {load_error}).")
            logger.debug(
                "QPdfDocument loaded print PDF: path=%s page_count=%d thread_id=%s",
                absolute_path,
                document.pageCount(),
                get_ident(),
            )
            page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
            page_size = page_rect.size().toSize()
            if document.pageCount() < 1 or page_size.isEmpty():
                raise RuntimeError("El PDF no contiene páginas imprimibles.")
            if not painter.begin(printer):
                raise RuntimeError("No se pudo iniciar el trabajo de impresión.")
            painter_started = True
            page_numbers = _selected_pdf_pages(self.settings, document.pageCount())
            for output_index, page_number in enumerate(page_numbers):
                if output_index and not printer.newPage():
                    raise RuntimeError("La impresora no pudo preparar la página siguiente.")
                image = document.render(page_number, page_size)
                if image.isNull():
                    raise RuntimeError(f"No se pudo renderizar la página {page_number + 1} del PDF.")
                painter.drawImage(page_rect, image)
            if not painter.end():
                painter_started = False
                raise RuntimeError("No se pudo finalizar el trabajo de impresión.")
            painter_started = False
            if printer.printerState() in (QPrinter.PrinterState.Error, QPrinter.PrinterState.Aborted):
                raise RuntimeError("El sistema no aceptó el trabajo de impresión.")
            accepted = True
        except Exception as exc:
            if painter_started:
                try:
                    printer.abort()
                except Exception:
                    pass
                try:
                    painter.end()
                except Exception:
                    pass
            error = str(exc)
        finally:
            if document is not None:
                try:
                    document.close()
                except Exception as exc:
                    if error is None:
                        error = str(exc)
                    accepted = False
            del painter
            del printer
            del document
            logger.debug(
                "Print send worker completed: path=%s accepted=%s thread_id=%s",
                self.path.resolve(strict=False),
                accepted,
                get_ident(),
            )
        self.finished.emit(accepted, error)


def _selected_pdf_pages(settings: PrinterSettings, page_count: int) -> list[int]:
    if settings.print_range == QPrinter.PrintRange.PageRange:
        if not settings.page_ranges.isEmpty():
            pages = [
                page_number - 1
                for page_number in range(
                    settings.page_ranges.firstPage(), settings.page_ranges.lastPage() + 1
                )
                if settings.page_ranges.contains(page_number)
            ]
            return [page for page in pages if 0 <= page < page_count]
        if settings.from_page > 0 or settings.to_page > 0:
            first = max(1, settings.from_page or 1)
            last = min(page_count, settings.to_page or page_count)
            return list(range(first - 1, last)) if first <= last else []
    return list(range(page_count))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pick List")
        self.setWindowIcon(QIcon(str(resource_path("assets/icons/pick_list.png"))))
        self.resize(1050, 720)
        self.setMinimumSize(760, 550)
        self._control_height = 34
        self.session = PickListSession.empty()
        self._closing = False
        self._processing = False
        self._result_received = False
        self._thread_finished = False
        self._worker_thread: QThread | None = None
        self._worker: ProcessWorker | None = None
        self._cancel_event: Event | None = None
        self._printing = False
        self._print_result_received = False
        self._print_thread_finished = False
        self._print_thread: QThread | None = None
        self._print_worker: PrintPdfWorker | None = None
        self._print_temp_dir: tempfile.TemporaryDirectory | None = None
        self._print_send_thread: QThread | None = None
        self._print_send_worker: PrintSendWorker | None = None
        self._print_send_done = True
        self._print_send_thread_finished = True
        self._metric_card_layout: QGridLayout | None = None
        self._metric_cards: list[QFrame] = []
        self._metric_values: dict[str, QLabel] = {}
        self._metric_columns = 0
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        heading = QLabel("Pick List · procesamiento local")
        heading.setAccessibleName("Pick List, procesamiento local")
        heading_font = self.font()
        heading_font.setPointSizeF(heading_font.pointSizeF() + 2)
        heading_font.setWeight(QFont.Weight.DemiBold)
        heading.setFont(heading_font)
        layout.addWidget(heading)
        actions = QHBoxLayout()
        self.add_button = QPushButton("Cargar PDFs")
        self.add_button.setObjectName("primary_action")
        self.add_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self.add_button.setMinimumHeight(36)
        self.add_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        add_font = self.add_button.font()
        add_font.setWeight(QFont.Weight.DemiBold)
        self.add_button.setFont(add_font)
        self.add_button.setAccessibleName("Cargar archivos PDF")
        self.add_button.setAccessibleDescription("Selecciona uno o varios PDFs para añadirlos a la sesión.")
        self.add_button.clicked.connect(self.choose_files)
        actions.addWidget(self.add_button)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.hide()
        self.progress.setMinimumWidth(135)
        self.progress.setAccessibleName("Progreso del procesamiento")
        self.progress.setAccessibleDescription("Avance del lote de documentos seleccionado.")
        actions.addWidget(self.progress)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("processing_status")
        progress_font = self.progress_label.font()
        progress_font.setWeight(QFont.Weight.DemiBold)
        self.progress_label.setFont(progress_font)
        self.progress_label.setAccessibleName("Estado del procesamiento")
        self.progress_label.hide()
        actions.addWidget(self.progress_label, 1)
        self.reset_button = QPushButton("Limpiar sesión")
        self.reset_button.setObjectName("reset_button")
        self.reset_button.setFlat(True)
        self.reset_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.reset_button.setMinimumHeight(self._control_height)
        self.reset_button.setAccessibleName("Limpiar sesión")
        self.reset_button.setAccessibleDescription("Elimina los documentos y productos de la sesión actual, después de confirmar.")
        self.reset_button.clicked.connect(self.reset_session)
        actions.addWidget(self.reset_button)
        layout.addLayout(actions)

        self.metrics = QWidget()
        self.metrics.setAccessibleName("Métricas de la sesión")
        self._metric_card_layout = QGridLayout(self.metrics)
        self._metric_card_layout.setContentsMargins(0, 0, 0, 0)
        self._metric_card_layout.setHorizontalSpacing(8)
        self._metric_card_layout.setVerticalSpacing(8)
        for key, title in (("invoices", "Facturas"), ("products", "Productos"),
                           ("caja", "Caja"), ("pack", "Pack"), ("unitario", "Unitario")):
            card = QFrame()
            card.setObjectName("metric_card")
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card.setBackgroundRole(QPalette.ColorRole.AlternateBase)
            card.setAutoFillBackground(True)
            card.setAccessibleName(f"Métrica {title}")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 6, 10, 6)
            card_layout.setSpacing(2)
            title_label = QLabel(title)
            title_label.setAccessibleName(f"Etiqueta de métrica {title}")
            value_label = QLabel("0")
            value_label.setObjectName("metric_value")
            value_font = self.font()
            value_font.setPointSizeF(value_font.pointSizeF() + 1)
            value_font.setWeight(QFont.Weight.DemiBold)
            value_label.setFont(value_font)
            card_layout.addWidget(title_label)
            card_layout.addWidget(value_label)
            self._metric_cards.append(card)
            self._metric_values[key] = value_label
        layout.addWidget(self.metrics)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar producto por descripción...")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Buscar productos por descripción")
        self.search.setAccessibleDescription("Filtra la lista de productos por texto de descripción. Atajo: buscar.")
        self.search.setMinimumHeight(self._control_height)
        self.search.textChanged.connect(self.refresh_products)
        filters.addWidget(self.search, 1)
        self.filter = QComboBox()
        self.filter.setAccessibleName("Filtrar por presentación")
        self.filter.setAccessibleDescription("Muestra todos los productos o filtra por Caja, Pack o Unitario.")
        self.filter.setMinimumHeight(self._control_height)
        self.filter.addItem("Todos", "all")
        for label, value in (("Caja", "caja"), ("Pack", "pack"), ("Unitario", "unitario")):
            self.filter.addItem(label, value)
        self.filter.currentIndexChanged.connect(self.refresh_products)
        filters.addWidget(self.filter)
        self.product_count = QLabel("Productos · 0 resultados")
        self.product_count.setAccessibleName("Cantidad de productos visibles")
        filters.addWidget(self.product_count)

        self.products = QTableWidget(0, 3)
        self.products.setHorizontalHeaderLabels(["Presentación", "Descripción", "Cantidad"])
        product_header = self.products.horizontalHeader()
        product_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        product_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        product_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        product_header_font = self.font()
        product_header_font.setWeight(QFont.Weight.DemiBold)
        product_header.setFont(product_header_font)
        self.products.setColumnWidth(0, 130)
        self.products.setColumnWidth(2, 125)
        self.products.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.products.setAlternatingRowColors(True)
        self.products.setShowGrid(False)
        self.products.verticalHeader().setVisible(False)
        self.products.verticalHeader().setDefaultSectionSize(30)
        self.products.setWordWrap(False)
        self.products.setAccessibleName("Productos consolidados")
        self.products.setAccessibleDescription("Productos de la sesión, filtrados por descripción y presentación.")
        self.products_empty = QLabel("Agrega archivos PDF para comenzar")
        self.products_empty.setObjectName("products_empty_state")
        self.products_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.products_empty.setWordWrap(True)
        self.products_empty.setAccessibleName("Estado de la lista de productos")
        self.products_stack = QStackedWidget()
        self.products_stack.addWidget(self.products_empty)
        self.products_stack.addWidget(self.products)

        self.products_panel = QWidget()
        products_layout = QVBoxLayout(self.products_panel)
        products_layout.setContentsMargins(0, 0, 0, 0)
        products_layout.setSpacing(6)
        product_toolbar = QHBoxLayout()
        product_toolbar.addLayout(filters, 1)
        products_layout.addLayout(product_toolbar)
        products_layout.addWidget(self.products_stack, 1)
        self.products_panel.setMinimumHeight(150)

        self.sources = QTableWidget(0, 5)
        self.sources.setHorizontalHeaderLabels(["Archivo", "Estado", "Páginas", "Requiere OCR", "Detalle"])
        source_header = self.sources.horizontalHeader()
        source_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        source_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        source_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        source_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        source_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        source_header_font = self.font()
        source_header_font.setWeight(QFont.Weight.DemiBold)
        source_header.setFont(source_header_font)
        self.sources.setColumnWidth(0, 255)
        self.sources.setColumnWidth(1, 105)
        self.sources.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sources.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.sources.setAlternatingRowColors(True)
        self.sources.setShowGrid(False)
        self.sources.verticalHeader().setVisible(False)
        self.sources.verticalHeader().setDefaultSectionSize(28)
        self.sources.setWordWrap(False)
        self.sources.setMinimumHeight(80)
        self.sources.setAccessibleName("Documentos y fuentes")
        self.sources.setAccessibleDescription("Estado, páginas, OCR y detalle de error de cada documento procesado.")
        sources_heading = QLabel("Documentos y fuentes")
        sources_heading.setBuddy(self.sources)
        self.sources_panel = QWidget()
        sources_layout = QVBoxLayout(self.sources_panel)
        sources_layout.setContentsMargins(0, 0, 0, 0)
        sources_layout.setSpacing(5)
        sources_layout.addWidget(sources_heading)
        sources_layout.addWidget(self.sources, 1)
        self.source_detail_label = QLabel("Detalle del documento seleccionado")
        self.source_detail_label.setAccessibleName("Detalle del documento seleccionado")
        self.source_detail_label.hide()
        layout.addWidget(self.source_detail_label)
        self.source_detail = QPlainTextEdit()
        self.source_detail.setReadOnly(True)
        self.source_detail.setMinimumHeight(30)
        self.source_detail.setMaximumHeight(52)
        self.source_detail.setAccessibleName("Mensaje completo del documento")
        self.source_detail.setAccessibleDescription("Texto seleccionable con el detalle completo del documento seleccionado.")
        self.source_detail.hide()
        sources_layout.addWidget(self.source_detail_label)
        sources_layout.addWidget(self.source_detail)
        self.sources_panel.setMinimumHeight(155)
        self.sources.currentCellChanged.connect(self.show_source_detail)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(7)
        self.splitter.addWidget(self.products_panel)
        self.splitter.addWidget(self.sources_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([420, 170])
        layout.addWidget(self.splitter, 1)

        self.exports_panel = QFrame()
        self.exports_panel.setObjectName("exports_panel")
        self.exports_panel.setFrameShape(QFrame.Shape.StyledPanel)
        exports_layout = QVBoxLayout(self.exports_panel)
        exports_layout.setContentsMargins(10, 6, 10, 8)
        exports_layout.setSpacing(5)
        exports_heading = QLabel("Exportaciones")
        exports_heading_font = exports_heading.font()
        exports_heading_font.setWeight(QFont.Weight.DemiBold)
        exports_heading.setFont(exports_heading_font)
        exports_layout.addWidget(exports_heading)
        exports = QHBoxLayout()
        self.export_buttons: list[QPushButton] = []
        self.print_buttons: list[QPushButton] = []
        for label, kind, default, description in (
            ("Lista Pickeo Bodega", "bodega", "Lista Pickeo Bodega.pdf",
             "Productos CAJA y resumen de facturas."),
            ("Lista Pickeo Local", "local", "Lista Pickeo Local.pdf",
             "Productos PACK y UNITARIO."),
        ):
            export_group = QVBoxLayout()
            export_description = QLabel(description)
            export_description.setAccessibleName(f"Contenido de {label}")
            export_group.addWidget(export_description)
            button = QPushButton(label)
            button.setObjectName("export_action")
            button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
            button.setMinimumHeight(self._control_height)
            button.setAccessibleName(f"Exportar {label}")
            button.setAccessibleDescription("Genera y guarda el PDF correspondiente.")
            export_handler = self._export_bodega_clicked if kind == "bodega" else self._export_local_clicked
            button.clicked.connect(export_handler)
            print_button = QPushButton(f"Imprimir {label.rsplit(' ', 1)[-1]}")
            print_button.setObjectName("print_action")
            print_button.setMinimumHeight(self._control_height)
            print_button.setAccessibleName(f"Imprimir {label.rsplit(' ', 1)[-1]}")
            print_button.setAccessibleDescription("Abre el diálogo del sistema para seleccionar opciones e impresora.")
            print_handler = self._print_bodega_clicked if kind == "bodega" else self._print_local_clicked
            print_button.clicked.connect(print_handler)
            action_row = QHBoxLayout()
            action_row.setSpacing(6)
            action_row.addWidget(button, 1)
            action_row.addWidget(print_button, 1)
            export_group.addLayout(action_row)
            exports.addLayout(export_group, 1)
            self.export_buttons.append(button)
            self.print_buttons.append(print_button)
        exports_layout.addLayout(exports)
        layout.addWidget(self.exports_panel)
        self.setCentralWidget(root)

        self.menuBar().setNativeMenuBar(True)
        window_menu = self.menuBar().addMenu("Ventana")
        self.minimize_action = QAction("Minimizar", self)
        self.minimize_action.setShortcut(QKeySequence("Ctrl+M"))
        self.minimize_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.minimize_action.triggered.connect(self.showMinimized)
        window_menu.addAction(self.minimize_action)

        self.add_shortcut = QShortcut(QKeySequence.StandardKey.Open, self)
        self.add_shortcut.setWhatsThis("Abrir el selector para cargar PDFs.")
        self.add_shortcut.activated.connect(self.choose_files)
        self.find_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        self.find_shortcut.setWhatsThis("Mover el foco a la búsqueda de productos.")
        self.find_shortcut.activated.connect(self.search.setFocus)
        QWidget.setTabOrder(self.add_button, self.search)
        QWidget.setTabOrder(self.search, self.filter)
        QWidget.setTabOrder(self.filter, self.products)
        QWidget.setTabOrder(self.products, self.sources)
        QWidget.setTabOrder(self.sources, self.export_buttons[0])
        QWidget.setTabOrder(self.export_buttons[0], self.export_buttons[1])
        QWidget.setTabOrder(self.export_buttons[1], self.print_buttons[0])
        QWidget.setTabOrder(self.print_buttons[0], self.print_buttons[1])
        QWidget.setTabOrder(self.print_buttons[1], self.reset_button)
        self._set_metric_columns(5)
        self.refresh_all()

    def _set_metric_columns(self, columns: int) -> None:
        if self._metric_card_layout is None or columns == self._metric_columns:
            return
        for card in self._metric_cards:
            self._metric_card_layout.removeWidget(card)
        for index, card in enumerate(self._metric_cards):
            self._metric_card_layout.addWidget(card, index // columns, index % columns)
        for column in range(5):
            self._metric_card_layout.setColumnStretch(column, 1 if column < columns else 0)
        self._metric_columns = columns

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._set_metric_columns(3 if self.width() < 780 else 5)

    def choose_files(self):
        if self._processing or self._worker_thread is not None:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Seleccionar PDFs", "", "PDF (*.pdf)")
        if not paths:
            return
        if len(paths) > 70:
            QMessageBox.warning(self, "Límite de lote", "Máximo permitido por lote: 70 PDFs.")
            return
        self._set_processing(True)
        self._result_received = False
        self._thread_finished = False
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        self.progress.show()
        self.progress_label.setText(f"Procesando documento 1 de {len(paths)}")
        self.progress_label.show()
        self._worker_thread = QThread(self)
        self._cancel_event = Event()
        self._worker = ProcessWorker(paths, self._cancel_event)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self.on_processed)
        self._worker.progress.connect(self.on_progress)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self.on_worker_thread_finished)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def on_processed(self, sources, error):
        self._result_received = True
        if self._closing:
            self._finish_processing_if_ready()
            return
        self.progress.hide()
        if error:
            self.progress_label.setText("Error al procesar el lote")
            QMessageBox.critical(self, "Error de procesamiento", error)
            sources = ()
        elif isinstance(sources, ProcessedBatch):
            self.session.add_batch(sources)
            sources = sources.sources
            failures = [source for source in sources if source.error]
            if failures:
                self.progress_label.setText(
                    f"Procesamiento finalizado · {len(failures)} documento(s) con error"
                )
            else:
                self.progress_label.setText("Procesamiento completado")
        elif sources is None:  # Cooperative cancellation: discard the entire batch.
            self.progress_label.setText("Procesamiento cancelado · no se añadieron resultados")
            sources = ()
        else:
            self.progress_label.setText("Procesamiento finalizado sin resultados")
            sources = ()
        failures = [source for source in sources if source.error]
        if failures:
            QMessageBox.warning(self, "Archivos con errores", "\n".join(f"{item.filename}: {item.error}" for item in failures))
        self.refresh_all()
        self._finish_processing_if_ready()

    def on_worker_thread_finished(self):
        self._thread_finished = True
        self._finish_processing_if_ready()

    def _finish_processing_if_ready(self) -> None:
        if not (self._result_received and self._thread_finished):
            return
        self._worker_thread = None
        self._worker = None
        self._cancel_event = None
        if not self._closing:
            self._set_processing(False)
        else:
            self.close()

    def _set_processing(self, active: bool) -> None:
        self._processing = active
        self.add_button.setEnabled(not active)
        self.reset_button.setEnabled(not active)
        self._update_action_buttons()

    def _update_action_buttons(self) -> None:
        products = self.session.consolidated()
        can_bodega = any(product.presentation == "caja" for product in products)
        can_local = any(product.presentation in {"unitario", "pack"} for product in products)
        enabled = not self._processing and not self._printing
        for index, has_exportable_products in enumerate((can_bodega, can_local)):
            self.export_buttons[index].setEnabled(enabled)
            self.print_buttons[index].setEnabled(enabled and has_exportable_products)

    def request_cancel(self) -> None:
        """Ask the worker to stop before it starts another document."""
        if self._cancel_event is not None:
            self._cancel_event.set()

    def on_progress(self, completed, total):
        if self._closing or not self._processing:
            return
        self.progress.setRange(0, total)
        self.progress.setValue(completed)
        if completed < total:
            current = completed + 1
            self.progress_label.setText(f"Procesando documento {current} de {total}")
        else:
            self.progress_label.setText("Finalizando procesamiento…")

    def refresh_all(self):
        products = self.session.consolidated()
        values = {
            "invoices": len(self.session.sources),
            "products": len(products),
            "caja": sum(p.presentation == "caja" for p in products),
            "pack": sum(p.presentation == "pack" for p in products),
            "unitario": sum(p.presentation == "unitario" for p in products),
        }
        for key, value in values.items():
            self._metric_values[key].setText(str(value))
        self._update_action_buttons()
        self.sources.setRowCount(len(self.session.sources))
        self.source_detail.clear()
        self.source_detail_label.hide()
        self.source_detail.hide()
        for row, source in enumerate(self.session.sources):
            is_failed = source.status == "failed" or bool(source.error)
            status = "Fallido" if is_failed else "Procesado" if source.status == "processed" else source.status
            ocr_label = "Sí" if source.requires_ocr else "No"
            values = (source.filename, status, str(source.page_count), ocr_label, source.error or "—")
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if value:
                    item.setToolTip(value)
                if col == 4 and source.error:
                    item.setToolTip(source.error)
                if col == 1:
                    icon = (QStyle.StandardPixmap.SP_MessageBoxCritical if is_failed
                            else QStyle.StandardPixmap.SP_DialogApplyButton)
                    item.setIcon(self.style().standardIcon(icon))
                    status_font = item.font()
                    status_font.setWeight(QFont.Weight.DemiBold)
                    item.setFont(status_font)
                self.sources.setItem(row, col, item)
        self.refresh_products()

    def refresh_products(self, *_):
        term, presentation = self.search.text().strip().lower(), self.filter.currentData()
        products = [p for p in self.session.consolidated()
                    if (presentation == "all" or p.presentation == presentation)
                    and term in p.description_exact.lower()]
        self.product_count.setText(f"Productos · {len(products)} resultados")
        self.products.setRowCount(len(products))
        if products:
            self.products_stack.setCurrentWidget(self.products)
        else:
            self.products_stack.setCurrentWidget(self.products_empty)
            all_products = self.session.consolidated()
            if not self.session.sources:
                message = "Agrega archivos PDF para comenzar"
            elif not all_products:
                if any(source.error or source.status == "failed" for source in self.session.sources):
                    message = "No hay productos disponibles. Consulta los detalles de los documentos con errores en Fuentes."
                else:
                    message = "Los documentos se procesaron, pero no hay productos disponibles."
            else:
                message = "No se encontraron productos con los filtros actuales"
            self.products_empty.setText(message)
        for row, product in enumerate(products):
            values = (product.presentation.upper(), product.description_exact,
                      f"{product.quantity if product.quantity is not None else '-'} {product.unit or ''}".strip())
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                elif col == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    item.setToolTip(product.description_exact)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.products.setItem(row, col, item)

    def show_source_detail(self, row: int, _column: int, _previous_row: int, _previous_column: int) -> None:
        if row < 0 or row >= len(self.session.sources):
            self.source_detail_label.hide()
            self.source_detail.hide()
            return
        source = self.session.sources[row]
        detail = source.error or "Documento procesado sin errores."
        self.source_detail.setPlainText(detail)
        self.source_detail_label.setText(f"Detalle de {source.filename}")
        self.source_detail_label.show()
        self.source_detail.show()

    def export_pdf(self, kind, default_name):
        if self._processing:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar PDF", str(Path.home() / default_name), "PDF (*.pdf)")
        if not path:
            return
        try:
            self.session.export(path, kind)
            QMessageBox.information(self, "Exportación lista", f"Archivo guardado en:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error de exportación", str(exc))

    def _export_bodega_clicked(self, _checked: bool = False) -> None:
        self.export_pdf("bodega", "Lista Pickeo Bodega.pdf")

    def _export_local_clicked(self, _checked: bool = False) -> None:
        self.export_pdf("local", "Lista Pickeo Local.pdf")

    def _print_bodega_clicked(self, _checked: bool = False) -> None:
        self.print_pdf("bodega")

    def _print_local_clicked(self, _checked: bool = False) -> None:
        self.print_pdf("local")

    def print_pdf(self, kind: str) -> None:
        if self._processing or self._printing:
            return
        if not QPrinterInfo.availablePrinters():
            QMessageBox.warning(self, "Sin impresoras", "No hay impresoras disponibles en el sistema.")
            return

        self._printing = True
        self._print_result_received = False
        self._print_thread_finished = False
        # Treat sending as pending while the native dialog is open. Its nested
        # event loop can deliver the export thread's finished signal before the
        # user accepts or cancels the dialog.
        self._print_send_done = False
        self._print_send_thread_finished = False
        self._update_action_buttons()
        self._print_thread = QThread(self)
        self._print_worker = PrintPdfWorker(self.session, kind)
        self._print_worker.moveToThread(self._print_thread)
        self._print_thread.started.connect(self._print_worker.run)
        self._print_worker.finished.connect(self._on_print_pdf_ready)
        self._print_worker.finished.connect(self._print_thread.quit)
        self._print_worker.finished.connect(self._print_worker.deleteLater)
        self._print_thread.finished.connect(self._on_print_thread_finished)
        self._print_thread.finished.connect(self._print_thread.deleteLater)
        self._print_thread.start()

    def _on_print_pdf_ready(self, path: str | None, error: str | None,
                            temporary_directory: tempfile.TemporaryDirectory | None) -> None:
        self._print_result_received = True
        self._print_temp_dir = temporary_directory
        if error:
            self._print_send_done = True
            self._print_send_thread_finished = True
            QMessageBox.critical(self, "Error al generar el PDF", error)
        elif self._closing:
            self._print_send_done = True
            self._print_send_thread_finished = True
        else:
            try:
                send_started = self._show_print_dialog_and_send(Path(path))
                if not send_started:
                    self._print_send_done = True
                    self._print_send_thread_finished = True
            except Exception as exc:
                self._print_send_done = True
                self._print_send_thread_finished = True
                QMessageBox.critical(self, "Error de impresión", str(exc))
        self._finish_print_flow_if_ready()

    def _show_print_dialog_and_send(self, path: Path) -> bool:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        try:
            result = dialog.exec()
        finally:
            dialog.close()
            dialog.deleteLater()
        if result != QPrintDialog.DialogCode.Accepted:
            return False
        if not printer.isValid():
            QMessageBox.critical(self, "Error de impresión", "La impresora seleccionada no es válida.")
            return False
        settings = PrinterSettings.from_printer(printer)
        del printer
        self._print_send_thread = QThread(self)
        self._print_send_worker = PrintSendWorker(path, settings)
        self._print_send_worker.moveToThread(self._print_send_thread)
        self._print_send_thread.started.connect(self._print_send_worker.run)
        self._print_send_worker.finished.connect(self._on_print_sent)
        self._print_send_worker.finished.connect(self._print_send_thread.quit)
        self._print_send_worker.finished.connect(self._print_send_worker.deleteLater)
        self._print_send_thread.finished.connect(self._on_print_send_thread_finished)
        self._print_send_thread.finished.connect(self._print_send_thread.deleteLater)
        self._print_send_thread.start()
        return True

    def _on_print_sent(self, accepted: bool, error: str | None) -> None:
        self._print_send_done = True
        if accepted:
            QMessageBox.information(self, "Impresión enviada", "El trabajo se envió a la cola de impresión.")
        elif error:
            QMessageBox.critical(self, "Error de impresión", error)
        self._finish_print_flow_if_ready()

    def _on_print_send_thread_finished(self) -> None:
        self._print_send_thread_finished = True
        self._finish_print_flow_if_ready()

    def _on_print_thread_finished(self) -> None:
        self._print_thread_finished = True
        self._finish_print_flow_if_ready()

    def _finish_print_flow_if_ready(self) -> None:
        if not (self._print_result_received and self._print_thread_finished
                and self._print_send_done and self._print_send_thread_finished):
            return
        self._print_thread = None
        self._print_worker = None
        self._print_send_thread = None
        self._print_send_worker = None
        if self._print_temp_dir is not None:
            _cleanup_print_temp_directory(self._print_temp_dir)
            self._print_temp_dir = None
        self._printing = False
        if not self._closing:
            self._update_action_buttons()
        else:
            self.close()

    def reset_session(self):
        if self._processing:
            return
        answer = QMessageBox.question(self, "Limpiar iteración", "Se eliminarán los datos de esta sesión. ¿Continuar?")
        if answer == QMessageBox.StandardButton.Yes:
            self.session.reset()
            self.refresh_all()

    def closeEvent(self, event):
        if self._printing:
            self._closing = True
            self.setEnabled(False)
            event.ignore()
            return
        if self._worker_thread is not None and not self._thread_finished:
            self._closing = True
            self.setEnabled(False)
            self.request_cancel()
            event.ignore()
            return
        self._closing = True
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Pick List")
    app.setWindowIcon(QIcon(str(resource_path("assets/icons/pick_list.png"))))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
