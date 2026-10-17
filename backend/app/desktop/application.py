from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from threading import Event

from app.services.consolidator import consolidate_product_rows
from app.services.document_summary import DocumentSummary
from app.services.extractor import ParsedProduct, extract_pdf
from app.services.pdf_exporter import export_vige_products


@dataclass(frozen=True)
class LocalSource:
    filename: str
    page_count: int
    requires_ocr: bool
    status: str
    error: str | None = None


@dataclass(frozen=True)
class SessionProduct:
    description_exact: str
    presentation: str
    quantity: int | None
    unit: str | None


@dataclass(frozen=True)
class ProcessedBatch:
    """Results produced off-thread and committed to a session on the UI thread."""

    sources: tuple[LocalSource, ...]
    products: tuple[SessionProduct, ...]
    summaries: tuple[DocumentSummary, ...]


def process_files(
    paths: list[str | Path],
    progress: Callable[[int, int], None] | None = None,
    cancel_event: Event | None = None,
) -> ProcessedBatch | None:
    """Extract a batch without reading or mutating a session."""
    if not paths:
        raise ValueError("Debes seleccionar al menos un PDF.")
    if len(paths) > 70:
        raise ValueError("Máximo permitido por lote: 70 PDFs.")
    batch_sources: list[LocalSource] = []
    batch_products: list[SessionProduct] = []
    batch_summaries: list[DocumentSummary] = []
    for index, raw_path in enumerate(paths, start=1):
        if cancel_event is not None and cancel_event.is_set():
            return None
        path = Path(raw_path)
        source: LocalSource
        products: tuple[SessionProduct, ...] = ()
        summary: DocumentSummary | None = None
        if path.suffix.lower() != ".pdf":
            source = LocalSource(path.name, 0, False, "failed", f"Archivo no PDF: {path.name}")
        else:
            try:
                result = extract_pdf(path)
                source = LocalSource(path.name, result.page_count, result.requires_ocr, "processed")
                products = tuple(
                    SessionProduct(p.descripcion_exacta, p.tipo_presentacion.lower(), p.cantidad, p.unit)
                    for p in result.products
                )
                summary = result.summary
            except Exception as exc:
                source = LocalSource(path.name, 0, False, "failed", str(exc)[:2000])
        # Do not add even the in-flight document to the temporary batch once
        # cancellation has been requested. The caller will discard the batch.
        if cancel_event is not None and cancel_event.is_set():
            return None
        batch_sources.append(source)
        batch_products.extend(products)
        if summary is not None:
            batch_summaries.append(summary)
        if progress is not None:
            progress(index, len(paths))
    if cancel_event is not None and cancel_event.is_set():
        return None
    return ProcessedBatch(tuple(batch_sources), tuple(batch_products), tuple(batch_summaries))


@dataclass
class PickListSession:
    """In-memory data for one desktop session; no database or remote services."""

    sources: list[LocalSource]
    products: list[SessionProduct]
    summaries: list[DocumentSummary]

    @classmethod
    def empty(cls) -> "PickListSession":
        return cls([], [], [])

    def add_batch(self, batch: ProcessedBatch) -> None:
        """Publish a completed batch as one UI-thread state transition."""
        sources = [*self.sources, *batch.sources]
        products = [*self.products, *batch.products]
        summaries = [*self.summaries, *batch.summaries]
        self.sources, self.products, self.summaries = sources, products, summaries

    def consolidated(self):
        return consolidate_product_rows(self.products)

    def export(self, path: str | Path, kind: str) -> Path:
        if kind == "bodega":
            return export_vige_products(self.consolidated(), Path(path), title="Lista Pickeo Bodega",
                                        allowed_presentations=("caja",), document_summaries=self.summaries,
                                        include_document_summary=True)
        if kind == "local":
            return export_vige_products(self.consolidated(), Path(path), title="Lista Pickeo Local",
                                        allowed_presentations=("unitario", "pack"))
        return export_vige_products(self.consolidated(), Path(path), title="Lista VIGE")

    def reset(self) -> None:
        self.sources.clear()
        self.products.clear()
        self.summaries.clear()
