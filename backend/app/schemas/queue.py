from pydantic import BaseModel


class BatchAcceptedOut(BaseModel):
    batch_id: str
    status: str
    total_files: int


class BatchTaskOut(BaseModel):
    source_file_id: int
    task_id: str
    status: str
    error_message: str | None


class BatchStatusOut(BaseModel):
    batch_id: str
    status: str
    total_files: int
    processed_files: int
    failed_files: int
    created_by_email: str
    created_at: str
    started_at: str | None
    completed_at: str | None
    tasks: list[BatchTaskOut]
