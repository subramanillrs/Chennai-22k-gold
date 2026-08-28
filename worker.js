// Cloudflare Worker example: secure Metals-API proxy.
// Store METALS_API_KEY as a Worker Secret. Never put it in the HTML.
//
// Routes:
// GET /api/gold       -> latest Chennai 22K/24K
// GET /api/gold/history?days=1095 -> historical daily observations
//
// Metals-API documentation confirms Chennai symbols CHEN-22k and CHEN-24k,
// historical coverage since 2023-12-14, latest and time-series endpoints.
// Adjust date chunk size to your subscription plan.

const API = "https://metals-api.com/api";

function cors() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET, OPTIONS"
  };
}
function json(data, status=200) {
  return new Response(JSON.stringify(data), {
    status, headers: {"Content-Type":"application/json", ...cors()}
  });
}
function ymd(d) { return d.toISOString().slice(0,10); }

async function metals(path, params, env) {
  const u = new URL(API + path);
  for (const [k,v] of Object.entries(params)) u.searchParams.set(k,v);
  u.searchParams.set("access_key", env.METALS_API_KEY);
  const r = await fetch(u.toString());
  const j = await r.json();
  if (!r.ok || j.success === false) throw new Error(j.error?.info || `Metals-API HTTP ${r.status}`);
  return j;
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null,{headers:cors()});
    const url = new URL(request.url);
    try {
      if (url.pathname === "/api/gold") {
        const j = await metals("/latest", {
          base: "USD", symbols: "CHEN-22k,CHEN-24k"
        }, env);
        const now = new Date((j.timestamp || Date.now()/1000)*1000);
        return json({
          success:true, source:"Metals-API",
          timestamp:j.timestamp, date:j.date,
          observations:[
            {date:j.date,time:now.toISOString().slice(11,19),city:"Chennai",purity:"22K",rate:j.rates["CHEN-22k"],source:"Metals-API",granularity:"daily"},
            {date:j.date,time:now.toISOString().slice(11,19),city:"Chennai",purity:"24K",rate:j.rates["CHEN-24k"],source:"Metals-API",granularity:"daily"}
          ]
        });
      }

      if (url.pathname === "/api/gold/history") {
        const requested = Math.min(1095, Math.max(1, Number(url.searchParams.get("days") || 1095)));
        const end = new Date(); end.setDate(end.getDate()-1);
        const start = new Date(end); start.setDate(start.getDate()-requested+1);

        // Fetch each symbol separately because Metals-API time-series plans can limit symbols.
        const observations=[];
        for (const [symbol,purity] of [["CHEN-22k","22K"],["CHEN-24k","24K"]]) {
          const j = await metals("/timeseries", {
            start_date: ymd(start), end_date: ymd(end), symbols: symbol
          }, env);
          for (const [date,obj] of Object.entries(j.rates || {})) {
            const rate = obj[symbol];
            if (Number.isFinite(Number(rate))) observations.push({
              date,time:"12:00:00",city:"Chennai",purity,rate:Number(rate),
              source:"Metals-API",granularity:"daily"
            });
          }
        }
        return json({success:true,source:"Metals-API",observations});
      }

      return json({success:false,error:"Not found"},404);
    } catch (e) {
      return json({success:false,error:String(e.message || e)},502);
    }
  }
};
