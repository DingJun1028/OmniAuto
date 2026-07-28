export default {
  async fetch(request, env, ctx) {
    return new Response("Hello from ai-station-proxy!\n", {
      headers: { "Content-Type": "text/plain" }
    });
  }
};
