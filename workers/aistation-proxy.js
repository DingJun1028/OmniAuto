/**
 * AI Station Proxy Worker
 * Forward requests for aistation.esggo.co to VPS
 */
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    
    // Target VPS
    const targetUrl = `http://161.118.252.147:8000${url.pathname}${url.search}`;
    
    // Forward request to VPS
    const modifiedRequest = new Request(targetUrl, {
      method: request.method,
      headers: request.headers,
      body: request.body,
    });
    
    try {
      const response = await fetch(modifiedRequest);
      
      // Return response with CORS headers
      const modifiedResponse = new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
      
      modifiedResponse.headers.set('Access-Control-Allow-Origin', '*');
      modifiedResponse.headers.set('X-Cloudflare-Worker', 'ai-station-proxy');
      
      return modifiedResponse;
    } catch (err) {
      return new Response(`AI Station Proxy Error: ${err.message}`, { 
        status: 502,
        headers: { 'Content-Type': 'text/plain' }
      });
    }
  },
};
