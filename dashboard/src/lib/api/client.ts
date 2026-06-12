/** API abstraction: every fetch goes through apiGet, which falls back to the
 * provided mock when the backend is unreachable or the endpoint 404s (not yet
 * built). The result carries `isMock` so the UI can badge it — mock data is
 * never silently presented as real. */

export interface ApiResult<T> {
  data: T;
  isMock: boolean;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export async function apiGet<T>(path: string, mock: T): Promise<ApiResult<T>> {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(5_000),
    });
    if (!response.ok) {
      if (response.status === 404) return { data: mock, isMock: true };
      throw new Error(`${response.status} ${response.statusText}`);
    }
    return { data: (await response.json()) as T, isMock: false };
  } catch {
    return { data: mock, isMock: true };
  }
}
