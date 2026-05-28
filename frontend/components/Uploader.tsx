"use client";

import type { FormEvent } from "react";
import { useState } from "react";

import { apiUrl } from "../lib/api";

type Props = {
  onUploaded: (batchId?: string) => Promise<void>;
  accessToken: string;
};

const MAX_PDFS_PER_BATCH = 70;
type BatchAcceptedResponse = {
  batch_id: string;
  status: string;
  total_files: number;
};

export function Uploader({ onUploaded, accessToken }: Props) {
  const [loading, setLoading] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string>("");

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem("pdfs") as HTMLInputElement | null;
    if (!input?.files || input.files.length === 0) return;
    setErrorMessage("");

    if (input.files.length > MAX_PDFS_PER_BATCH) {
      setErrorMessage(`Solo puedes subir hasta ${MAX_PDFS_PER_BATCH} PDFs por lote.`);
      return;
    }

    const payload = new FormData();
    Array.from(input.files).forEach((file) => payload.append("files", file));

    setLoading(true);
    try {
      const response = await fetch(apiUrl("/api/upload"), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${accessToken}`
        },
        body: payload
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: string } | null;
        setErrorMessage(body?.detail ?? "Error al subir el lote de PDFs.");
        return;
      }
      const data = (await response.json()) as BatchAcceptedResponse;
      await onUploaded(data.batch_id);
      form.reset();
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="rounded-xl bg-white p-6 shadow-md">
      <h2 className="mb-2 text-xl font-semibold">Carga de PDFs</h2>
      <p className="mb-2 text-sm text-slate-600">Máximo por lote: {MAX_PDFS_PER_BATCH} facturas PDF.</p>
      <input name="pdfs" type="file" accept="application/pdf" multiple className="mb-4 block w-full" />
      {errorMessage ? <p className="mb-3 text-sm font-medium text-rose-700">{errorMessage}</p> : null}
      <button
        type="submit"
        disabled={loading}
        className="rounded-md bg-teal-700 px-4 py-2 font-semibold text-white disabled:opacity-50"
      >
        {loading ? "Procesando..." : "Subir y procesar"}
      </button>
    </form>
  );
}
