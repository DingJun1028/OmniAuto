export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Admin
    if (request.method === 'POST' && url.pathname === '/__admin') {
      return new Response(JSON.stringify({ status: 'ok', worker: 'ai-station-proxy', version: 12 }), {
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Proxy to VPS via nginx (port 80, which proxies to Docker 8000)
    const targetUrl = `http://161.118.252.147${url.pathname}${url.search}`;
    const newHeaders = new Headers(request.headers);
    newHeaders.set('Host', 'aistation.esggo.co');
    newHeaders.set('X-Forwarded-Host', 'aistation.esggo.co');
    newHeaders.set('X-Forwarded-Proto', 'https');

    try {
      const resp = await fetch(targetUrl, {
        method: request.method,
        headers: newHeaders,
        body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
      });
      const outHeaders = new Headers(resp.headers);
      outHeaders.set('Access-Control-Allow-Origin', '*');
      return new Response(resp.body, { status: resp.status, headers: outHeaders });
    } catch (err) {
      return new Response(JSON.stringify({
        status: 'proxy-failed', error: err.message,
        hint: 'Check VPS nginx + Docker are running'
      }), { status: 502, headers: { 'Content-Type': 'application/json' } });
    }
  }
};
