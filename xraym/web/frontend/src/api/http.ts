
export interface ApiResponse<T = any> {
  success: boolean;
  msg: string;
  obj: T;
}

export function getUrl(path: string): string {
  const base = (window as any).BASE_PATH || '';
  const cleanBase = base.replace(/\/+$/, '');
  const cleanPath = path.startsWith('/') ? path : '/' + path;
  return cleanBase + cleanPath;
}

export async function request<T = any>(
  path: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const url = getUrl(path);

  const headers = new Headers(options.headers || {});
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  let body = options.body;
  if (body && typeof body === 'object' && !(body instanceof FormData)) {
    body = JSON.stringify(body);
  }

  try {
    const response = await fetch(url, {
      ...options,
      headers,
      body,
    });

    if (response.status === 401) {
      // Session expired -> redirect back to login page
      const base = (window as any).BASE_PATH || '';
      const cleanBase = base.replace(/\/+$/, '');
      window.location.href = cleanBase + '/#/login';
      throw new Error('Unauthorized');
    }

    const data = await response.json();
    return data;
  } catch (err: any) {
    console.error('API Error:', err);
    return {
      success: false,
      msg: err?.message || 'Server error atau format respon tidak valid',
      obj: null as any,
    };
  }
}
