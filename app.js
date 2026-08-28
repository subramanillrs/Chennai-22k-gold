const $ = s => document.querySelector(s);

let historyData = [];
let selectedDays = 1095;

const fmt = n =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0
  }).format(Number(n));

const dateFmt = d =>
  new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric"
  }).format(new Date(d + "T00:00:00"));

async function getJSON(file) {
  const response = await fetch(
    "./" + file + "?v=" + Date.now(),
    { cache: "no-store" }
  );

  if (!response.ok) {
    throw new Error(file + " HTTP " + response.status);
  }

  return response.json();
}

async function load() {
  try {
    const [today, history] = await Promise.all([
      getJSON("today.json"),
      getJSON("history.json")
    ]);

    if (
      !today ||
      !today.rates ||
      !today.rates["22K"] ||
      !today.rates["24K"]
    ) {
      throw new Error("Invalid today.json");
    }

    historyData = Array.isArray(history.records)
      ? history.records
      : [];

    renderToday(today);
    renderHistory();
    drawChart();

  } catch (error) {

    console.error(error);

    $("#status").textContent =
      "Data unavailable — check JSON files";

    $("#sourceText").textContent =
      "today.json or history.json could not be loaded.";
  }
}

function renderToday(data) {

  const gold22 = data.rates["22K"];
  const gold24 = data.rates["24K"];

  $("#price8").textContent =
    fmt(gold22.per8g);

  $("#price1").textContent =
    fmt(gold22.perGram) + " / gram";

  $("#p24").textContent =
    fmt(gold24.per8g);

  $("#p22").textContent =
    fmt(gold22.perGram);

  $("#dataDate").textContent =
    dateFmt(data.rateDate);

  $("#lastChange").textContent =
    data.lastChangeTime || "Not published";

  const change = data.changeFromPrevious;

  if (change == null) {

    $("#change").textContent =
      "No previous verified comparison";

  } else {

    $("#change").textContent =
      `${change >= 0 ? "▲" : "▼"} ${fmt(
        Math.abs(change)
      )}/g vs previous rate`;

  }

  $("#change").className =
    "change " + (change >= 0 ? "up" : "down");

  $("#status").textContent =
    data.status === "verified-today"
      ? "Verified today"
      : "Latest verified rate";

  $("#sourceText").innerHTML =
    `${data.sourceSummary || "Source information unavailable"}<br>
     <span class="${
       data.status === "verified-today"
         ? "good"
         : "warn"
     }">
     ${data.freshnessNote || ""}
     </span>`;
}

function renderHistory() {

  const rows = historyData.slice(0, 30);

  $("#history").innerHTML =
    rows.map((row, index) => {

      const previous =
        historyData[index + 1]?.rate22k;

      const difference =
        previous == null
          ? null
          : Number(row.rate22k) -
            Number(previous);

      return `
        <div class="row">

          <div>
            <div class="date">
              ${dateFmt(row.date)}
            </div>

            <div class="session">
              ${row.session || "Daily"}
              ·
              ${row.source || "verified"}
            </div>
          </div>

          <strong>
            ${fmt(row.rate22k)}
          </strong>

          <span class="${
            difference == null
              ? ""
              : difference >= 0
                ? "up"
                : "down"
          }">

            ${
              difference == null
                ? ""
                : (difference >= 0 ? "▲ " : "▼ ") +
                  fmt(Math.abs(difference))
            }

          </span>

        </div>
      `;

    }).join("");
}

function drawChart() {

  const canvas = $("#chart");

  if (!canvas) return;

  const ctx = canvas.getContext("2d");

  const ratio =
    window.devicePixelRatio || 1;

  const width =
    canvas.clientWidth;

  const height =
    canvas.clientHeight;

  canvas.width =
    width * ratio;

  canvas.height =
    height * ratio;

  ctx.setTransform(
    ratio,
    0,
    0,
    ratio,
    0,
    0
  );

  ctx.clearRect(
    0,
    0,
    width,
    height
  );

  const cutoff =
    Date.now() -
    selectedDays * 86400000;

  const data =
    historyData
      .filter(item =>
        new Date(
          item.date + "T23:59:59"
        ).getTime() >= cutoff
      )
      .slice()
      .reverse();

  if (data.length < 2) {

    ctx.fillStyle = "#8f9ab4";

    ctx.font =
      "13px system-ui";

    ctx.fillText(
      "Not enough historical data",
      12,
      30
    );

    return;
  }

  const values =
    data.map(item =>
      Number(item.rate22k)
    );

  const minimum =
    Math.min(...values);

  const maximum =
    Math.max(...values);

  const padding = 18;

  ctx.strokeStyle =
    "#33405d";

  ctx.lineWidth = 1;

  for (let i = 0; i < 4; i++) {

    const y =
      padding +
      i *
        (height - padding * 2) /
        3;

    ctx.beginPath();

    ctx.moveTo(0, y);

    ctx.lineTo(width, y);

    ctx.stroke();
  }

  ctx.beginPath();

  data.forEach((item, index) => {

    const x =
      index *
        (width - 8) /
        (data.length - 1) +
      4;

    const y =
      padding +
      (
        maximum -
        Number(item.rate22k)
      ) /
        (maximum - minimum || 1) *
        (height - padding * 2);

    if (index === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }

  });

  ctx.strokeStyle =
    "#f0c96b";

  ctx.lineWidth = 2.5;

  ctx.stroke();
}

document
  .querySelectorAll(".ranges button")
  .forEach(button => {

    button.onclick = () => {

      document
        .querySelectorAll(".ranges button")
        .forEach(x =>
          x.classList.remove("active")
        );

      button.classList.add("active");

      selectedDays =
        Number(button.dataset.days);

      drawChart();
    };

  });

$("#refresh").onclick = load;

window.addEventListener(
  "resize",
  drawChart
);

load();
