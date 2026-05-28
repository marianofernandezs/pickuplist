export type Product = {
  id: number;
  source_file_id: number;
  page_number: number;
  sku: string | null;
  description_exact: string;
  quantity: number | null;
  unit: string | null;
  presentation: string;
  observations: string | null;
};

export type SourceFile = {
  id: number;
  filename: string;
  status: string;
  page_count: number;
  requires_ocr: boolean;
};
