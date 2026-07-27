const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export async function apiRequest<T>(
  path: string,
  options: RequestInit & { token?: string } = {}
): Promise<T> {
  const { token, ...fetchOptions } = options
  const res = await fetch(`${API_URL}${path}`, {
    ...fetchOptions,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(fetchOptions.headers ?? {}),
    },
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    // Le code HTTP est exposé sur l'erreur : les appelants doivent pouvoir réagir
    // spécifiquement (ex. 403 sur un thread_id périmé -> repartir sur un fil neuf).
    const err = new Error(error.detail || `HTTP ${res.status}`) as Error & { status?: number }
    err.status = res.status
    throw err
  }
  return res.json()
}
