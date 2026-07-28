export default {
  async fetch(request, env, ctx) {
    // Ping endpoint - check worker is alive
    if (request.method === 'GET' && new URL(request.url).pathname === '/ping') {
      return new Response('pong', { status: 200 });
    }

    // Deploy endpoint - auto-create DNS + route + deploy
    if (request.method === 'POST' && new URL(request.url).pathname === '/deploy') {
      const auth = request.headers.get('X-Auth-Key');
      if (auth !== env.AUTH_KEY) {
        return new Response('Unauthorized', { status: 401 });
      }

      const results = [];

      // 1) Create DNS A record via API
      const zoneId = '8dda3653e490290412f7be84a84e0dc9';
      const token = env.CF_API_TOKEN;
      
      const dnsResp = await fetch(`https://api.cloudflare.com/client/v4/zones/${zoneId}/dns_records`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: 'A', name: 'aistation', content: '161.118.252.147', ttl: 120, proxied: true
        })
      });
      const dnsResult = await dnsResp.json();
      results.push({ step: 'dns', success: dnsResult.success, result: dnsResult });

      return new Response(JSON.stringify({ results }, null, 2), {
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Proxy endpoint - forward to VPS
    const url = new URL(request.url);
    const targetUrl = `http://161.118.252.147:8000${url.pathname}${url.search}`;
    
    try {
      const resp = await fetch(targetUrl, {
        method: request.method,
        headers: request.headers,
        body: request.body,
      });
      return new Response(resp.body, {
        status: resp.status,
        statusText: resp.statusText,
        headers: resp.headers,
      });
    } catch (err) {
      return new Response(`Proxy Error: ${err.message}`, { status: 502 });
    }
  }
};
