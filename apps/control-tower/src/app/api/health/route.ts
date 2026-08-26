const healthResponse = {
  service: "control-tower-web",
  status: "ok",
} as const;

export function GET() {
  return Response.json(healthResponse, {
    headers: {
      "Cache-Control": "no-store",
    },
  });
}
