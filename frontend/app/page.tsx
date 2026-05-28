"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Uploader } from "../components/Uploader";
import { apiUrl } from "../lib/api";
import { authHeader, clearAccessToken, getAccessToken } from "../lib/auth";
import type { Product, SourceFile } from "../lib/types";

type AuthUser = {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
};

type ProductFilter = "all" | "caja" | "pack" | "unitario";
type BatchTaskStatus = {
  source_file_id: number;
  task_id: string;
  status: string;
  error_message: string | null;
};
type BatchStatus = {
  batch_id: string;
  status: string;
  total_files: number;
  processed_files: number;
  failed_files: number;
  tasks: BatchTaskStatus[];
};

export default function DashboardPage() {
  const router = useRouter();
  const [accessToken, setAccessToken] = useState<string>("");
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [sources, setSources] = useState<SourceFile[]>([]);
  const [resetting, setResetting] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [currentBatchId, setCurrentBatchId] = useState<string>("");
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null);

  const [search, setSearch] = useState<string>("");
  const [filter, setFilter] = useState<ProductFilter>("all");

  const forceLogout = useCallback((): void => {
    clearAccessToken();
    setAccessToken("");
    setCurrentUser(null);
    router.replace("/login");
  }, [router]);

  const loadData = useCallback(
    async (token: string): Promise<void> => {
      const [pRes, sRes] = await Promise.all([
        fetch(apiUrl("/api/products"), { headers: authHeader(token) }),
        fetch(apiUrl("/api/sources"), { headers: authHeader(token) })
      ]);

      if (pRes.status === 401 || sRes.status === 401) {
        forceLogout();
        return;
      }

      const productsJson = (await pRes.json()) as Product[];
      const sourcesJson = (await sRes.json()) as SourceFile[];
      setProducts(productsJson);
      setSources(sourcesJson);
    },
    [forceLogout]
  );

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }

    setAccessToken(token);
    fetch(apiUrl("/api/auth/me"), { headers: authHeader(token) })
      .then(async (response) => {
        if (!response.ok) {
          forceLogout();
          return;
        }
        const user = (await response.json()) as AuthUser;
        setCurrentUser(user);
        await loadData(token);
      })
      .finally(() => setLoading(false));
  }, [forceLogout, loadData, router]);

  const resetData = useCallback(async (): Promise<void> => {
    if (!accessToken) return;
    setResetting(true);
    try {
      await fetch(apiUrl("/api/reset"), {
        method: "POST",
        headers: authHeader(accessToken)
      });
      await loadData(accessToken);
    } finally {
      setResetting(false);
    }
  }, [accessToken, loadData]);

  const downloadPdf = useCallback(
    async (url: string, filename: string): Promise<void> => {
      if (!accessToken) return;
      const response = await fetch(url, { headers: authHeader(accessToken) });
      if (!response.ok) return;

      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(blobUrl);
    },
    [accessToken]
  );

  const filteredProducts = useMemo(() => {
    const term = search.trim().toLowerCase();
    return products.filter((product) => {
      const matchesFilter = filter === "all" || product.presentation === filter;
      const matchesSearch = term.length === 0 || product.description_exact.toLowerCase().includes(term);
      return matchesFilter && matchesSearch;
    });
  }, [filter, products, search]);

  const metrics = useMemo(() => {
    const caja = products.filter((product) => product.presentation === "caja").length;
    const pack = products.filter((product) => product.presentation === "pack").length;
    const unitario = products.filter((product) => product.presentation === "unitario").length;
    return {
      total: products.length,
      facturas: sources.length,
      caja,
      pack,
      unitario
    };
  }, [products, sources]);

  useEffect(() => {
    if (!currentBatchId || !accessToken) return;
    let stopped = false;

    const poll = async (): Promise<void> => {
      const response = await fetch(apiUrl(`/api/batches/${currentBatchId}`), {
        headers: authHeader(accessToken)
      });
      if (!response.ok) return;
      const data = (await response.json()) as BatchStatus;
      if (stopped) return;
      setBatchStatus(data);

      const doneStatuses = new Set(["completed", "failed", "completed_with_errors"]);
      if (doneStatuses.has(data.status)) {
        await loadData(accessToken);
        return;
      }
      setTimeout(() => {
        void poll();
      }, 2000);
    };

    void poll();

    return () => {
      stopped = true;
    };
  }, [accessToken, currentBatchId, loadData]);

  if (loading) {
    return <main className="mx-auto max-w-3xl p-8">Cargando dashboard...</main>;
  }

  if (!currentUser || !accessToken) {
    return null;
  }

  return (
    <main className="min-h-screen px-4 pb-10 pt-6 md:px-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="rounded-3xl border border-[var(--ap-line)] bg-white/90 p-5 shadow-[0_16px_50px_rgba(14,58,47,0.12)] backdrop-blur-sm md:p-6">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="mb-1 text-xs uppercase tracking-[0.18em] text-[var(--ap-green-700)]">AricaPlast · VIGE</p>
              <h1 className="brand-title text-3xl text-[var(--ap-green-900)] md:text-4xl">Centro de Operaciones</h1>
              <p className="mt-1 text-sm text-slate-600">Carga de facturas, consolidación y exportación de pickeo en un solo panel.</p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full border border-[var(--ap-line)] bg-[var(--ap-sand-50)] px-3 py-1 text-sm text-slate-700">
                {currentUser.email}
              </span>
              <button
                type="button"
                onClick={() => forceLogout()}
                className="rounded-xl bg-slate-800 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700"
              >
                Cerrar sesión
              </button>
            </div>
          </div>
        </header>

        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <div className="rounded-2xl border border-[var(--ap-line)] bg-white p-4 shadow-sm">
            <p className="text-xs uppercase tracking-[0.14em] text-slate-500">Productos</p>
            <p className="mt-1 text-3xl font-bold text-[var(--ap-green-900)]">{metrics.total}</p>
          </div>
          <div className="rounded-2xl border border-[var(--ap-line)] bg-white p-4 shadow-sm">
            <p className="text-xs uppercase tracking-[0.14em] text-slate-500">Facturas</p>
            <p className="mt-1 text-3xl font-bold text-[var(--ap-green-900)]">{metrics.facturas}</p>
          </div>
          <div className="rounded-2xl border border-[var(--ap-line)] bg-white p-4 shadow-sm">
            <p className="text-xs uppercase tracking-[0.14em] text-slate-500">Cajas</p>
            <p className="mt-1 text-3xl font-bold text-[var(--ap-green-900)]">{metrics.caja}</p>
          </div>
          <div className="rounded-2xl border border-[var(--ap-line)] bg-white p-4 shadow-sm">
            <p className="text-xs uppercase tracking-[0.14em] text-slate-500">Pack</p>
            <p className="mt-1 text-3xl font-bold text-[var(--ap-green-900)]">{metrics.pack}</p>
          </div>
          <div className="rounded-2xl border border-[var(--ap-line)] bg-white p-4 shadow-sm">
            <p className="text-xs uppercase tracking-[0.14em] text-slate-500">Unitario</p>
            <p className="mt-1 text-3xl font-bold text-[var(--ap-green-900)]">{metrics.unitario}</p>
          </div>
        </section>

        <section className="rounded-3xl border border-[var(--ap-line)] bg-white p-6 shadow-sm">
      <Uploader
        onUploaded={async (batchId?: string) => {
          if (batchId) {
            setCurrentBatchId(batchId);
          }
          await loadData(accessToken);
        }}
        accessToken={accessToken}
      />

      {batchStatus ? (
        <section className="rounded-3xl border border-[var(--ap-line)] bg-white p-6 shadow-sm">
          <h2 className="text-xl font-semibold text-[var(--ap-green-900)]">Estado de procesamiento</h2>
          <p className="mt-2 text-sm text-slate-600">
            Lote: <strong>{batchStatus.batch_id}</strong> · Estado: <strong>{batchStatus.status}</strong>
          </p>
          <p className="mt-1 text-sm text-slate-600">
            Procesadas: {batchStatus.processed_files}/{batchStatus.total_files} · Fallidas: {batchStatus.failed_files}
          </p>
        </section>
      ) : null}
        </section>

        <section className="rounded-3xl border border-[var(--ap-line)] bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <h2 className="text-2xl font-semibold text-[var(--ap-green-900)]">Productos consolidados</h2>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  const confirmed = window.confirm("Esto borrará productos, fuentes y archivos cargados. ¿Continuar?");
                  if (confirmed) {
                    void resetData();
                  }
                }}
                disabled={resetting}
                className="rounded-xl bg-rose-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-rose-600 disabled:opacity-50"
              >
                {resetting ? "Limpiando..." : "Limpiar iteración"}
              </button>
              <button
                type="button"
                onClick={() => {
                  void downloadPdf(apiUrl("/api/export/bodega"), "Lista Pickeo Bodega.pdf");
                }}
                className="rounded-xl bg-emerald-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-600"
              >
                Lista Pickeo Bodega
              </button>
              <button
                type="button"
                onClick={() => {
                  void downloadPdf(apiUrl("/api/export/local"), "Lista Pickeo Local.pdf");
                }}
                className="rounded-xl bg-teal-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-teal-600"
              >
                Lista Pickeo Local
              </button>
            </div>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-[1fr_auto]">
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Buscar producto por descripción..."
              className="w-full rounded-xl border border-[var(--ap-line)] bg-[var(--ap-sand-50)] px-4 py-3 text-sm outline-none transition focus:border-[var(--ap-green-500)] focus:ring-4 focus:ring-emerald-100"
            />
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setFilter("all")}
                className={`rounded-xl px-3 py-2 text-sm font-semibold transition ${
                  filter === "all" ? "bg-[var(--ap-green-800)] text-white" : "bg-slate-100 text-slate-700"
                }`}
              >
                Todos
              </button>
              <button
                type="button"
                onClick={() => setFilter("caja")}
                className={`rounded-xl px-3 py-2 text-sm font-semibold transition ${
                  filter === "caja" ? "bg-[var(--ap-green-800)] text-white" : "bg-slate-100 text-slate-700"
                }`}
              >
                Caja
              </button>
              <button
                type="button"
                onClick={() => setFilter("pack")}
                className={`rounded-xl px-3 py-2 text-sm font-semibold transition ${
                  filter === "pack" ? "bg-[var(--ap-green-800)] text-white" : "bg-slate-100 text-slate-700"
                }`}
              >
                Pack
              </button>
              <button
                type="button"
                onClick={() => setFilter("unitario")}
                className={`rounded-xl px-3 py-2 text-sm font-semibold transition ${
                  filter === "unitario" ? "bg-[var(--ap-green-800)] text-white" : "bg-slate-100 text-slate-700"
                }`}
              >
                Unitario
              </button>
            </div>
          </div>

          <ul className="mt-5 grid gap-2">
            {filteredProducts.map((product) => (
              <li
                key={product.id}
                className="flex flex-col gap-2 rounded-xl border border-[var(--ap-line)] bg-[var(--ap-sand-50)] p-3 md:flex-row md:items-center md:justify-between"
              >
                <div className="text-sm text-[var(--ap-ink)]">
                  <span className="mr-2 inline-flex rounded-lg bg-emerald-100 px-2 py-1 text-xs font-bold text-[var(--ap-green-900)]">
                    {product.presentation.toUpperCase()}
                  </span>
                  {product.description_exact}
                </div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Cantidad: {product.quantity ?? "-"} {product.unit?.toUpperCase() ?? ""}
                </div>
              </li>
            ))}
            {filteredProducts.length === 0 ? (
              <li className="rounded-xl border border-dashed border-[var(--ap-line)] bg-white p-6 text-center text-sm text-slate-500">
                No hay productos que coincidan con el filtro actual.
              </li>
            ) : null}
          </ul>
        </section>

        <section className="rounded-3xl border border-[var(--ap-line)] bg-white p-6 shadow-sm">
          <h2 className="text-2xl font-semibold text-[var(--ap-green-900)]">Trazabilidad de fuentes</h2>
          <div className="mt-4 grid gap-2">
            {sources.map((source) => (
              <div
                key={source.id}
                className="rounded-xl border border-[var(--ap-line)] bg-[var(--ap-sand-50)] px-4 py-3 text-sm text-slate-700"
              >
                <strong>{source.filename}</strong> · estado: {source.status} · páginas: {source.page_count} · requiere OCR:{" "}
                {String(source.requires_ocr)}
              </div>
            ))}
            {sources.length === 0 ? (
              <div className="rounded-xl border border-dashed border-[var(--ap-line)] bg-white p-6 text-center text-sm text-slate-500">
                Aún no hay facturas cargadas.
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
