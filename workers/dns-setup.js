/**
 * Create DNS A Record for AI Station
 * Trigger this worker once to create the DNS record
 * Route: create-dns.esggo.co
 */
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    
    if (request.method === 'POST' && url.pathname === '/setup') {
      // Create DNS A record using the Cloudflare API
      const cfToken = request.headers.get('X-CF-Token') || '';
      
      const zoneId = '8dda3653e490290412f7be84a84e0dc9';
      const dnsResult = await fetch(
        `https://api.cloudflare.com/client/v4/zones/${zoneId}/dns_records`,
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${cfToken}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            type: 'A',
            name: 'aistation',
            content: '161.118.252.147',
            ttl: 120,
            proxied: true,
          }),
        }
      );
      
      const result = await dnsResult.json();
      
      return new Response(JSON.stringify(result, null, 2), {
        headers: { 'Content-Type': 'application/json' },
      });
    }
    
    return new Response('Send POST /setup with X-CF-Token header', {
      headers: { 'Content-Type': 'text/plain' },
    });
  },
};
