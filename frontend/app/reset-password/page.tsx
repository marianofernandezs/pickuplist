"use client";

import type { FormEvent } from "react";
import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { apiUrl } from "../../lib/api";

function ResetPasswordContent() {
  const searchParams = useSearchParams();
  const [token, setToken] = useState<string>("");
  const [password, setPassword] = useState<string>("");
  const [confirmPassword, setConfirmPassword] = useState<string>("");
  const [message, setMessage] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);

  useEffect(() => {
    const tokenFromQuery = searchParams.get("token") ?? "";
    if (tokenFromQuery) {
      setToken(tokenFromQuery);
    }
  }, [searchParams]);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setMessage("");

    if (password !== confirmPassword) {
      setMessage("La confirmación no coincide con la nueva contraseña.");
      return;
    }

    setLoading(true);
    try {
      const response = await fetch(apiUrl("/api/auth/reset-password"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password })
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: string } | null;
        setMessage(body?.detail ?? "No se pudo actualizar la contraseña.");
        return;
      }

      setMessage("Contraseña actualizada. Ya puedes iniciar sesión.");
      setPassword("");
      setConfirmPassword("");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-8">
      <section className="w-full max-w-xl rounded-3xl border border-[var(--ap-line)] bg-white/80 p-8 shadow-[0_20px_70px_rgba(15,58,47,0.15)] backdrop-blur-sm">
        <p className="mb-2 text-xs uppercase tracking-[0.22em] text-[var(--ap-green-700)]">AricaPlast</p>
        <h1 className="brand-title text-4xl text-[var(--ap-green-900)]">Cambiar contraseña</h1>
        <p className="mt-2 text-sm text-slate-600">Ingresa el token de recuperación y define una nueva contraseña segura.</p>

        <form className="mt-6 space-y-4" onSubmit={onSubmit}>
          <label className="block text-sm font-semibold text-[var(--ap-green-900)]" htmlFor="token">
            Token de recuperación
          </label>
          <input
            id="token"
            type="text"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            required
            minLength={20}
            className="w-full rounded-xl border border-[var(--ap-line)] bg-white px-4 py-3 text-sm outline-none transition focus:border-[var(--ap-green-500)] focus:ring-4 focus:ring-emerald-100"
            placeholder="Pega el token recibido"
          />

          <label className="block text-sm font-semibold text-[var(--ap-green-900)]" htmlFor="new-password">
            Nueva contraseña
          </label>
          <input
            id="new-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            minLength={8}
            className="w-full rounded-xl border border-[var(--ap-line)] bg-white px-4 py-3 text-sm outline-none transition focus:border-[var(--ap-green-500)] focus:ring-4 focus:ring-emerald-100"
            placeholder="Mínimo 8 caracteres"
          />

          <label className="block text-sm font-semibold text-[var(--ap-green-900)]" htmlFor="confirm-password">
            Confirmar contraseña
          </label>
          <input
            id="confirm-password"
            type="password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            required
            minLength={8}
            className="w-full rounded-xl border border-[var(--ap-line)] bg-white px-4 py-3 text-sm outline-none transition focus:border-[var(--ap-green-500)] focus:ring-4 focus:ring-emerald-100"
            placeholder="Repite la nueva contraseña"
          />

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-xl bg-[var(--ap-green-800)] px-4 py-3 font-semibold text-white transition hover:bg-[var(--ap-green-700)] disabled:opacity-60"
          >
            {loading ? "Actualizando..." : "Actualizar contraseña"}
          </button>
        </form>

        {message ? <p className="mt-4 rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-700">{message}</p> : null}

        <div className="mt-6 text-sm">
          <Link href="/login" className="font-semibold text-[var(--ap-green-800)] hover:underline">
            Volver a iniciar sesión
          </Link>
        </div>
      </section>
    </main>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center px-4 py-8">
          <section className="w-full max-w-xl rounded-3xl border border-[var(--ap-line)] bg-white/80 p-8 shadow-[0_20px_70px_rgba(15,58,47,0.15)] backdrop-blur-sm">
            <p className="text-sm text-slate-600">Cargando formulario de recuperación...</p>
          </section>
        </main>
      }
    >
      <ResetPasswordContent />
    </Suspense>
  );
}
