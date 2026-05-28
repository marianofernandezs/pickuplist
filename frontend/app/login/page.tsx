"use client";

import type { FormEvent } from "react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { apiUrl } from "../../lib/api";
import { authHeader, getAccessToken, setAccessToken } from "../../lib/auth";

type AuthUser = {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
};

type LoginResponse = {
  access_token: string;
  token_type: string;
  user: AuthUser;
};

export default function LoginPage() {
  const router = useRouter();
  const [checkingSession, setCheckingSession] = useState<boolean>(true);
  const [email, setEmail] = useState<string>("");
  const [password, setPassword] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string>("");

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      setCheckingSession(false);
      return;
    }

    fetch(apiUrl("/api/auth/me"), { headers: authHeader(token) })
      .then((response) => {
        if (response.ok) {
          router.replace("/");
          return;
        }
        setCheckingSession(false);
      })
      .catch(() => setCheckingSession(false));
  }, [router]);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setErrorMessage("");
    setLoading(true);

    try {
      const response = await fetch(apiUrl("/api/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as {
          detail?: string;
        } | null;
        setErrorMessage(body?.detail ?? "No se pudo iniciar sesión.");
        return;
      }

      const data = (await response.json()) as LoginResponse;
      setAccessToken(data.access_token);
      router.replace("/");
    } finally {
      setLoading(false);
    }
  }

  if (checkingSession) {
    return <main className="mx-auto max-w-2xl p-8">Verificando sesión...</main>;
  }

  return (
    <main className="min-h-screen">
      <section className="grid min-h-screen w-full overflow-hidden md:grid-cols-[1.15fr_0.85fr]">
        <aside className="login-noise relative overflow-hidden bg-[var(--ap-green-900)] p-8 text-white md:p-12">
          <Image
            src="/images/login-hero.webp"
            alt="Productos de empaque AricaPlast"
            fill
            className="object-cover opacity-35"
            priority
          />
          <div className="absolute inset-0 bg-gradient-to-br from-[var(--ap-green-900)]/85 via-[var(--ap-green-800)]/75 to-[var(--ap-green-700)]/78" />
          <div className="relative z-10 flex h-full flex-col justify-between">
            <div>
              <p className="mb-3 inline-flex rounded-full border border-white/20 px-3 py-1 text-xs uppercase tracking-[0.2em] text-white/90">
                AricaPlast
              </p>
              <h1 className="brand-title text-4xl leading-tight md:text-5xl">
                Portal de Gestión Pick List
              </h1>
              <p className="mt-4 max-w-md text-sm text-emerald-50/90 md:text-base">
                Acceso seguro para consolidación de facturas, trazabilidad y
                listas de pickeo.
              </p>
            </div>

            <div className="mt-10 rounded-2xl border border-white/20 bg-white/10 p-5 backdrop-blur-sm">
              <p className="text-xs uppercase tracking-[0.18em] text-emerald-100/90">
                Operación
              </p>
              <ul className="mt-3 space-y-2 text-sm text-emerald-50">
                <li>Hasta 70 facturas PDF por lote.</li>
                <li>Consolidación por tipo de presentación.</li>
                <li>Exportación separada para local y bodega.</li>
              </ul>
            </div>
          </div>
        </aside>

        <div className="flex items-center justify-center bg-[var(--ap-sand-50)] p-7 md:p-12">
          <div className="w-full max-w-xl rounded-3xl border border-[var(--ap-line)] bg-white px-6 py-7 shadow-[0_20px_60px_rgba(15,58,47,0.12)] md:translate-y-8 md:px-8 md:py-9">
            <div className="mb-6">
              <h2 className="brand-title text-3xl text-[var(--ap-green-900)]">
                Iniciar sesión
              </h2>
              <p className="mt-1 text-sm text-slate-600">
                Solo usuarios autorizados pueden entrar al sistema.
              </p>
            </div>

            <form onSubmit={onSubmit} className="space-y-4">
              <label
                className="block text-sm font-semibold text-[var(--ap-green-900)]"
                htmlFor="login-email"
              >
                Correo corporativo
              </label>
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="usuario@empresa.cl"
                className="w-full rounded-xl border border-[var(--ap-line)] bg-white px-4 py-3 text-sm outline-none transition focus:border-[var(--ap-green-500)] focus:ring-4 focus:ring-emerald-100"
                required
              />

              <label
                className="block text-sm font-semibold text-[var(--ap-green-900)]"
                htmlFor="login-password"
              >
                Contraseña
              </label>
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="••••••••"
                className="w-full rounded-xl border border-[var(--ap-line)] bg-white px-4 py-3 text-sm outline-none transition focus:border-[var(--ap-green-500)] focus:ring-4 focus:ring-emerald-100"
                required
                minLength={8}
              />

              {errorMessage ? (
                <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700">
                  {errorMessage}
                </p>
              ) : null}

              <button
                className="w-full rounded-xl bg-[var(--ap-green-800)] px-4 py-3 font-semibold text-white shadow-lg shadow-emerald-900/20 transition hover:bg-[var(--ap-green-700)] disabled:opacity-60"
                type="submit"
                disabled={loading}
              >
                {loading ? "Ingresando..." : "Entrar al sistema"}
              </button>
            </form>

            <div className="mt-6 flex items-center justify-between rounded-xl border border-[var(--ap-line)] bg-white px-4 py-3 text-sm">
              <span className="text-slate-600">¿Olvidaste tu contraseña?</span>
              <Link
                href="/forgot-password"
                className="font-semibold text-[var(--ap-green-800)] hover:underline"
              >
                Recuperar acceso
              </Link>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
