const $=s=>document.querySelector(s);
let historyData=[];
let selectedDays=1095;
const fmt=n=>new Intl.NumberFormat("en-IN",{style:"currency",currency:"INR",maximumFractionDigits:0}).format(n);
const dateFmt=d=>new Intl.DateTimeFormat("en-IN",{day:"2-digit",month:"short",year:"numeric"}).format(new Date(d+"T00:00:00"));

async function load(){
  try{
    const [t,h]=await Promise.all([
      fetch("data/today.json?"+Date.now(),{cache:"no-store"}).then(r=>r.json()),
      fetch("data/history.json?"+Date.now(),{cache:"no-store"}).then(r=>r.json())
    ]);
    historyData=h.records||[];
    renderToday(t); renderHistory(); draw();
  }catch(e){
    $("#status").textContent="Data unavailable — no stale value substituted";
    $("#sourceText").textContent="The app could not load its verified data files.";
  }
}
function renderToday(t){
  $("#price8").textContent=fmt(t.rates["22K"].per8g);
  $("#price1").textContent=fmt(t.rates["22K"].perGram)+"/gram";
  $("#p24").textContent=fmt(t.rates["24K"].per8g);
  $("#p22").textContent=fmt(t.rates["22K"].perGram);
  $("#dataDate").textContent=dateFmt(t.rateDate);
  $("#lastChange").textContent=t.lastChangeTime||"Not published";
  const c=t.changeFromPrevious;
  $("#change").textContent=c==null?"No prior verified comparison":`${c>=0?"▲":"▼"} ${fmt(Math.abs(c))}/g vs previous verified rate`;
  $("#change").className="change "+(c>=0?"up":"down");
  $("#status").textContent=t.status==="verified-today"?"Verified today":"Latest verified rate · not pretending an old snapshot is today's";
  $("#sourceText").innerHTML=`${t.sourceSummary}<br><span class="${t.status==="verified-today"?"good":"warn"}">${t.freshnessNote}</span>`;
}
function renderHistory(){
  const rows=historyData.slice(0,16);
  $("#history").innerHTML=rows.map((r,i)=>{
    const prev=historyData[i+1]?.rate22k;
    const diff=prev==null?null:r.rate22k-prev;
    return `<div class="row"><div><div class="date">${dateFmt(r.date)}</div><div class="session">${r.session} · ${r.source||"verified"}</div></div><strong>${fmt(r.rate22k)}</strong><span class="${diff==null?"":diff>=0?"up":"down"}">${diff==null?"":(diff>=0?"▲ ":"▼ ")+fmt(Math.abs(diff))}</span></div>`
  }).join("");
}
function draw(){
  const c=$("#chart"),ctx=c.getContext("2d"),dpr=devicePixelRatio||1,w=c.clientWidth,h=c.clientHeight;
  c.width=w*dpr;c.height=h*dpr;ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);
  const data=historyData.filter(x=>new Date(x.date)>=new Date(Date.now()-selectedDays*864e5)).slice().reverse();
  if(data.length<2)return;
  const vals=data.map(x=>x.rate22k),min=Math.min(...vals),max=Math.max(...vals),pad=18;
  ctx.strokeStyle="#33405d";ctx.lineWidth=1;
  for(let i=0;i<4;i++){const y=pad+i*(h-pad*2)/3;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke()}
  ctx.beginPath();
  data.forEach((p,i)=>{const x=i*(w-8)/(data.length-1)+4,y=pad+(max-p.rate22k)/(max-min||1)*(h-pad*2);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});
  ctx.strokeStyle="#f0c96b";ctx.lineWidth=2.5;ctx.stroke();
}
document.querySelectorAll(".ranges button").forEach(b=>b.onclick=()=>{document.querySelectorAll(".ranges button").forEach(x=>x.classList.remove("active"));b.classList.add("active");selectedDays=+b.dataset.days;draw()});
$("#refresh").onclick=load;
window.addEventListener("resize",draw); load();