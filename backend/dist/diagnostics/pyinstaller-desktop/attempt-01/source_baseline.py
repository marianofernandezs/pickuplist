from __future__ import annotations

import json
from pathlib import Path

import fitz
from app.desktop.application import PickListSession, process_files

backend = Path(__file__).resolve().parents[3] / "backend"
fixture = backend / "tests" / "fixtures" / "DTE-PDF-76353833-8-33-111801.pdf"
out = Path(__file__).resolve().parent / "source-baseline"
batch = process_files([fixture])
if batch is None or not batch.sources or batch.sources[0].status != "processed":
    raise SystemExit(f"source extraction failed: {batch!r}")
session = PickListSession.empty()
session.add_batch(batch)
exports = {}
for kind, name in (("bodega", "source-bodega.pdf"), ("local", "source-local.pdf")):
    path = session.export(out / name, kind)
    with fitz.open(path) as pdf:
        exports[kind] = {
            "pages": len(pdf),
            "text": "\n".join(page.get_text("text") for page in pdf),
        }
products = [
    {
        "description": product.description_exact,
        "presentation": product.presentation,
        "quantity": product.quantity,
        "unit": product.unit,
    }
    for product in session.consolidated()
]
report = {
    "fixture": fixture.name,
    "sources": [source.__dict__ for source in batch.sources],
    "products": products,
    "summaries": [summary.__dict__ for summary in batch.summaries],
    "metrics": {
        "invoices": len(session.sources),
        "products": len(products),
        "caja": sum(p["presentation"] == "caja" for p in products),
        "pack": sum(p["presentation"] == "pack" for p in products),
        "unitario": sum(p["presentation"] == "unitario" for p in products),
    },
    "exports": exports,
}
(out / "source-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"fixture": report["fixture"], "metrics": report["metrics"],
                  "products": len(products),
                  "summaries": report["summaries"],
                  "bodega_pages": exports["bodega"]["pages"],
                  "local_pages": exports["local"]["pages"]}, ensure_ascii=False, indent=2))
