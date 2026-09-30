// Cloudflare Pages Function — Proxy reverso dinâmico para o backend leve
export async function onRequest(context) {
  const url = new URL(context.request.url);
  const backendBase = (context.env.BACKEND_URL || 'https://aleff-backend.onrender.com').replace(/\/$/, '');
  const targetUrl = `${backendBase}${url.pathname}${url.search}`;

  const requestHeaders = new Headers(context.request.headers);
  requestHeaders.set('X-Forwarded-Host', url.host);
  requestHeaders.set('X-Forwarded-Proto', url.protocol.replace(':', ''));

  const newRequest = new Request(targetUrl, {
    method: context.request.method,
    headers: requestHeaders,
    body: context.request.body,
    redirect: 'manual'
  });

  try {
    return await fetch(newRequest);
  } catch (err) {
    return new Response(JSON.stringify({
      status: 'error',
      message: 'Backend indisponível no momento. Verifique a URL do Render.',
      error: String(err)
    }), {
      status: 502,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}
