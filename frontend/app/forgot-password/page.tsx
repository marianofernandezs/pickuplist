"use client";

import type { FormEvent } from "react";
import Link from "next/link";
import { useState } from "react";

import { apiUrl } from "../../lib/api";

type ForgotPasswordResponse = {
  message: string;
  reset_token?: string | null;
  reset_link?: string | null;
};

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [message, setMessage] = useState<string>("");
  const [resetLink, setResetLink] = useState<string>("");

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    setResetLink("");

    try {
      const response = await fetch(apiUrl("/api/auth/forgot-password"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email })
      });

      const body = (await response.json().catch(() => null)) as ForgotPasswordResponse | null;
      setMessage(body?.message ?? "Solicitud procesada.");
      if (body?.reset_link) {
        setResetLink(body.reset_link);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-8">
      <section className="w-full max-w-xl rounded-3xl border border-[var(--ap-line)] bg-white/80 p-8 shadow-[0_20px_70px_rgba(15,58,47,0.15)] backdrop-blur-sm">
        <p className="mb-2 text-xs uppercase tracking-[0.22em] text-[var(--ap-green-700)]">AricaPlast</p>
        <h1 className="brand-title text-4xl text-[var(--ap-green-900)]">Recuperar contraseña</h1>
        <p className="mt-2 text-sm text-slate-600">
          Te enviaremos un enlace para cambiar tu contraseña. La integración de correo será el siguiente paso.
        </p>

        <form className="mt-6 space-y-4" onSubmit={onSubmit}>
          <label className="block text-sm font-semibold text-[var(--ap-green-900)]" htmlFor="forgot-email">
            Correo de usuario
          </label>
          <input
            id="forgot-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            className="w-full rounded-xl border border-[var(--ap-line)] bg-white px-4 py-3 text-sm outline-none transition focus:border-[var(--ap-green-500)] focus:ring-4 focus:ring-emerald-100"
            placeholder="usuario@empresa.cl"
          />
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-xl bg-[var(--ap-green-800)] px-4 py-3 font-semibold text-white transition hover:bg-[var(--ap-green-700)] disabled:opacity-60"
          >
            {loading ? "Enviando..." : "Enviar enlace de recuperación"}
          </button>
        </form>

        {message ? <p className="mt-4 rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-700">{message}</p> : null}

        {resetLink ? (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            <p>Modo local: enlace temporal de recuperación</p>
            <a className="mt-2 inline-block break-all font-semibold underline" href={resetLink}>
              {resetLink}
            </a>
          </div>
        ) : null}

        <div className="mt-6 text-sm">
          <Link href="/login" className="font-semibold text-[var(--ap-green-800)] hover:underline">
            Volver a iniciar sesión
          </Link>
        </div>
      </section>
    </main>
  );
}
