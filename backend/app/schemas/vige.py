from pydantic import BaseModel


class ProductOut(BaseModel):
    id: int
    source_file_id: int
    page_number: int
    sku: str | None
    description_exact: str
    quantity: int | None
    unit: str | None
    presentation: str
    observations: str | None

    model_config = {"from_attributes": True}


class SourceFileOut(BaseModel):
    id: int
    filename: str
    status: str
    page_count: int
    requires_ocr: bool

    model_config = {"from_attributes": True}
