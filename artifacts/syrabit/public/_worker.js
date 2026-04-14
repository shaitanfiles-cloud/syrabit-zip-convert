export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      const response = await env.ASSETS.fetch(request);
      if (response.status === 404) {
        const accept = request.headers.get("Accept") || "";
        const isNavigationRequest =
          request.method === "GET" && accept.includes("text/html");
        if (isNavigationRequest) {
          const indexResponse = await env.ASSETS.fetch(
            new URL("/", url.origin),
          );
          return new Response(indexResponse.body, {
            headers: indexResponse.headers,
            status: 200,
          });
        }
        return response;
      }
      return response;
    } catch {
      const indexResponse = await env.ASSETS.fetch(new URL("/", url.origin));
      return new Response(indexResponse.body, {
        headers: indexResponse.headers,
        status: 200,
      });
    }
  },
};
