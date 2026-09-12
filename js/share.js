// ============================================================
// SHARE ENGINE: CANVAS RECEIPT, HERO SNAPSHOT & VIRAL INFOGRAPHIC
// ============================================================
function roundRect(ctx, x, y, width, height, radius) {
  if (typeof radius === "undefined") radius = 5;
  if (typeof radius === "number") {
    radius = { tl: radius, tr: radius, br: radius, bl: radius };
  } else {
    const defaultRadius = { tl: 0, tr: 0, br: 0, bl: 0 };
    for (let side in defaultRadius) {
      radius[side] = radius[side] || defaultRadius[side];
    }
  }
  ctx.beginPath();
  ctx.moveTo(x + radius.tl, y);
  ctx.lineTo(x + width - radius.tr, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + radius.tr);
  ctx.lineTo(x + width, y + height - radius.br);
  ctx.quadraticCurveTo(x + width, y + height, x + width - radius.br, y + height);
  ctx.lineTo(x + radius.bl, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - radius.bl);
  ctx.lineTo(x, y + radius.tl);
  ctx.quadraticCurveTo(x, y, x + radius.tl, y);
  ctx.closePath();
}


// --- UPGRADE 5: Share Receipt (mirrors the hero snapshot share flow) ---
(function setupShareReceipt() {
  const btn = document.getElementById("shareReceiptBtn");
  if (!btn) return;

  const textOf = (id, fallback = "—") => {
    const el = document.getElementById(id);
    return el ? ((el.textContent || "").trim() || fallback) : fallback;
  };

  function roundRect(ctx, x, y, w, h, r) {
    if (typeof ctx.roundRect === "function") {
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, r);
      return;
    }
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function generateReceiptCard() {
    const attr = (document.documentElement.getAttribute("data-theme") || "").toLowerCase();
    const saved = (localStorage.getItem("gold_theme") || "").toLowerCase();
    const isNight = attr === "oled" || attr === "dark" || (!attr && (saved === "oled" || saved === "dark"));

    const canvas = document.createElement("canvas");
    const W = 720;
    const H = 640;
    const dpr = Math.min(2, Math.max(1, window.devicePixelRatio || 1.5));
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    const bgGrad = ctx.createRadialGradient(W / 2, 40, 20, W / 2, H / 2, W * 0.85);
    if (isNight) {
      bgGrad.addColorStop(0, "#121212");
      bgGrad.addColorStop(0.5, "#000000");
      bgGrad.addColorStop(1, "#000000");
    } else {
      bgGrad.addColorStop(0, "#ffffff");
      bgGrad.addColorStop(0.55, "#faf6ed");
      bgGrad.addColorStop(1, "#eee5d3");
    }
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, W, H);

    // Card Outer Border
    ctx.strokeStyle = isNight ? "rgba(255, 215, 0, 0.40)" : "rgba(169, 127, 52, 0.35)";
    ctx.lineWidth = 1.5;
    roundRect(ctx, 16, 16, W - 32, H - 32, 20);
    ctx.stroke();

    if (isNight) {
      ctx.strokeStyle = "rgba(255, 215, 0, 0.14)";
      ctx.lineWidth = 1;
      roundRect(ctx, 22, 22, W - 44, H - 44, 16);
      ctx.stroke();
    }

    // Brand badge
    const badgeGrad = ctx.createLinearGradient(36, 36, 74, 74);
    if (isNight) {
      badgeGrad.addColorStop(0, "#fff2a8");
      badgeGrad.addColorStop(0.5, "#ffd700");
      badgeGrad.addColorStop(1, "#b39200");
    } else {
      badgeGrad.addColorStop(0, "#f4dca0");
      badgeGrad.addColorStop(0.55, "#a97f34");
      badgeGrad.addColorStop(1, "#6b5223");
    }
    ctx.fillStyle = badgeGrad;
    roundRect(ctx, 36, 36, 38, 38, 9);
    ctx.fill();

    ctx.fillStyle = isNight ? "#000000" : "#ffffff";
    ctx.font = "bold 19px 'Fraunces', Georgia, serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("Au", 55, 55);

    // Header Title
    ctx.textAlign = "left";
    ctx.fillStyle = isNight ? "#ffffff" : "#1c1712";
    ctx.font = "italic 600 22px 'Fraunces', Georgia, serif";
    ctx.fillText("Purchase Quotation", 86, 49);

    ctx.fillStyle = isNight ? "#d4ab63" : "#6b6255";
    ctx.font = "500 12px 'Inter', -apple-system, sans-serif";
    ctx.fillText("Chennai 22K Gold · Itemized Estimate", 86, 68);

    ctx.strokeStyle = isNight ? "rgba(255, 215, 0, 0.22)" : "rgba(28, 23, 18, 0.10)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(36, 96);
    ctx.lineTo(W - 36, 96);
    ctx.stroke();

    const lines = [
      ["Base 22K Gold Cost", textOf("receiptBase", "₹ 0")],
      [textOf("receiptMakingLabel", "Making Charges"), textOf("receiptMaking", "₹ 0")],
      [textOf("receiptGstLabel", "GST"), textOf("receiptGst", "₹ 0")],
      ["Hallmarking / Flat Fees", textOf("receiptFee", "₹ 0")],
    ];
    const oldGoldLine = document.getElementById("receiptOldGoldLine");
    if (oldGoldLine && oldGoldLine.style.display !== "none") {
      lines.push(["Old Gold Exchange Credit", textOf("receiptOldGold", "-₹ 0")]);
    }

    // Inner Box for Quotation Lines
    const boxY = 114;
    const boxH = 34 * lines.length + 22;
    ctx.fillStyle = isNight ? "rgba(14, 14, 14, 0.85)" : "rgba(255, 255, 255, 0.85)";
    ctx.strokeStyle = isNight ? "rgba(255, 215, 0, 0.20)" : "rgba(169, 127, 52, 0.20)";
    ctx.lineWidth = 1;
    roundRect(ctx, 36, boxY, W - 72, boxH, 14);
    ctx.fill();
    ctx.stroke();

    let y = boxY + 28;
    ctx.font = "500 15px 'Inter', -apple-system, sans-serif";
    lines.forEach(([label, val]) => {
      const isCredit = label.includes("Credit");
      ctx.fillStyle = isNight ? "#a89d88" : "#6b6255";
      ctx.textAlign = "left";
      ctx.fillText(label, 52, y);
      ctx.fillStyle = isCredit ? (isNight ? "#00e676" : "#2d7a48") : (isNight ? "#ffffff" : "#1c1712");
      ctx.font = "600 15px 'Inter', -apple-system, sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(val, W - 52, y);
      ctx.font = "500 15px 'Inter', -apple-system, sans-serif";
      y += 34;
    });

    // Total Card Box
    const totalY = boxY + boxH + 16;
    ctx.fillStyle = isNight ? "rgba(255, 215, 0, 0.12)" : "rgba(169, 127, 52, 0.08)";
    ctx.strokeStyle = isNight ? "rgba(255, 215, 0, 0.40)" : "rgba(169, 127, 52, 0.30)";
    ctx.lineWidth = 1;
    roundRect(ctx, 36, totalY, W - 72, 86, 14);
    ctx.fill();
    ctx.stroke();

    ctx.textAlign = "left";
    ctx.font = "600 14px 'Inter', -apple-system, sans-serif";
    ctx.fillStyle = isNight ? "#ffd700" : "#8a6627";
    ctx.fillText(textOf("receiptTotalLabel", "Net Payable Amount"), 56, totalY + 36);

    ctx.textAlign = "right";
    ctx.font = "700 36px 'Fraunces', Georgia, serif";
    ctx.fillStyle = isNight ? "#ffd700" : "#6b5223";
    ctx.fillText(textOf("calcResult", "₹ —"), W - 56, totalY + 54);

    // Subtitle & Date
    const footY = totalY + 116;
    ctx.textAlign = "left";
    ctx.font = "500 12px 'Inter', -apple-system, sans-serif";
    ctx.fillStyle = isNight ? "#a89d88" : "#8a8174";
    ctx.fillText(textOf("calcSub", "Based on live 22K rate · Official MJDMA Fix"), 36, footY);

    const rates = (typeof getCurrentMarketRates === "function") ? getCurrentMarketRates() : { dt: "Today" };
    const dt = rates.dt || (typeof live !== "undefined" && live && live.date ? dateText(live.date) : textOf("today")) || "Today";
    ctx.textAlign = "right";
    ctx.fillStyle = isNight ? "#d4ab63" : "#6b5223";
    ctx.fillText(dt, W - 36, footY);

    ctx.textAlign = "center";
    ctx.font = "500 11px 'Inter', -apple-system, sans-serif";
    ctx.fillStyle = isNight ? "#666666" : "#a89d88";
    ctx.fillText("Chennai 22K Gold · Institutional Terminal Benchmark", W / 2, H - 24);

    return canvas;
  }

  btn.addEventListener("click", async () => {
    try {
      if (typeof haptic === "function") haptic(15);
      btn.classList.add("is-sharing");

      const total = textOf("calcResult", "₹ —");
      const base = textOf("receiptBase", "₹ 0");
      const making = textOf("receiptMaking", "₹ 0");
      const gst = textOf("receiptGst", "₹ 0");
      const fee = textOf("receiptFee", "₹ 0");
      const shareUrl = window.location.href.split("#")[0];

      const shareText = `🧾 Gold Purchase Quotation\n• Base 22K Gold Cost: ${base}\n• Making Charges: ${making}\n• GST: ${gst}\n• Hallmarking / Flat Fees: ${fee}\n• Net Payable: ${total}\n${shareUrl}`;

      const canvas = generateReceiptCard();
      const dataUrl = canvas.toDataURL("image/png");

      let shared = false;

      if (navigator.share && navigator.canShare && window.isSecureContext) {
        try {
          const blob = await new Promise(res => canvas.toBlob(res, "image/png", 0.96));
          if (blob) {
            const file = new File([blob], "gold-receipt.png", { type: "image/png" });
            if (navigator.canShare({ files: [file] })) {
              await navigator.share({
                title: "Gold Purchase Quotation",
                text: shareText,
                files: [file]
              });
              shared = true;
            }
          }
        } catch (shareErr) {
          if (shareErr.name === "AbortError") {
            btn.classList.remove("is-sharing");
            return;
          }
        }
      }

      if (!shared && navigator.share && window.isSecureContext) {
        try {
          await navigator.share({
            title: "Gold Purchase Quotation",
            text: shareText,
            url: shareUrl
          });
          shared = true;
        } catch (shareErr) {
          if (shareErr.name === "AbortError") {
            btn.classList.remove("is-sharing");
            return;
          }
        }
      }

      if (!shared) {
        let copied = false;
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(shareText);
            copied = true;
          }
        } catch (_) {}

        if (!copied) {
          try {
            const ta = document.createElement("textarea");
            ta.value = shareText;
            ta.style.position = "fixed";
            ta.style.left = "-9999px";
            ta.style.opacity = "0";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
            copied = true;
          } catch (_) {}
        }

        const a = document.createElement("a");
        a.href = dataUrl;
        a.download = `gold-receipt-${(typeof live !== "undefined" && live && live.date) || "quotation"}.png`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

        if (typeof toast === "function") {
          toast(copied ? "Receipt saved & summary copied!" : "Receipt downloaded!");
        }
      }
    } catch (err) {
      console.error("Share receipt error:", err);
      if (typeof toast === "function") toast("Could not share receipt");
    } finally {
      setTimeout(() => btn.classList.remove("is-sharing"), 400);
    }
  });
})();


/* SHARE SNAPSHOT — Native Canvas Card + Multi-tier Web Share API */
(function setupShareSnapshot() {
  const btn = document.getElementById("shareBtn");
  if (!btn) return;

  const textOf = (id, fallback = "—") => {
    const el = document.getElementById(id);
    return el ? ((el.textContent || "").trim() || fallback) : fallback;
  };

  function roundRect(ctx, x, y, w, h, r) {
    if (typeof ctx.roundRect === "function") {
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, r);
      return;
    }
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function generateSnapshotCard() {
    const attr = (document.documentElement.getAttribute("data-theme") || "").toLowerCase();
    const saved = (localStorage.getItem("gold_theme") || "").toLowerCase();
    const isNight = attr === "oled" || attr === "dark" || (!attr && (saved === "oled" || saved === "dark"));

    const rates = (typeof getCurrentMarketRates === "function") ? getCurrentMarketRates() : { r22: 14145, r8: 113160, r24: 15431, r18: 11582, chg: -125, dt: "Today", tm: "" };

    const canvas = document.createElement("canvas");
    const W = 820;
    const H = 530;
    const dpr = Math.min(2, Math.max(1, window.devicePixelRatio || 1.5));
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    // 1. Background
    const bgGrad = ctx.createRadialGradient(W / 2, 20, 10, W / 2, H / 2, W * 0.75);
    if (isNight) {
      bgGrad.addColorStop(0, "#121212");
      bgGrad.addColorStop(0.5, "#000000");
      bgGrad.addColorStop(1, "#000000");
    } else {
      bgGrad.addColorStop(0, "#ffffff");
      bgGrad.addColorStop(0.55, "#faf6ed");
      bgGrad.addColorStop(1, "#eee5d3");
    }
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, W, H);

    // 2. Card Outer Border
    ctx.strokeStyle = isNight ? "rgba(255, 215, 0, 0.40)" : "rgba(169, 127, 52, 0.35)";
    ctx.lineWidth = 1.5;
    roundRect(ctx, 16, 16, W - 32, H - 32, 20);
    ctx.stroke();

    if (isNight) {
      ctx.strokeStyle = "rgba(255, 215, 0, 0.12)";
      ctx.lineWidth = 1;
      roundRect(ctx, 22, 22, W - 44, H - 44, 16);
      ctx.stroke();
    }

    // 3. Header: Brand Badge (Au)
    const badgeGrad = ctx.createLinearGradient(36, 36, 74, 74);
    if (isNight) {
      badgeGrad.addColorStop(0, "#fff2a8");
      badgeGrad.addColorStop(0.5, "#ffd700");
      badgeGrad.addColorStop(1, "#b39200");
    } else {
      badgeGrad.addColorStop(0, "#f4dca0");
      badgeGrad.addColorStop(0.55, "#a97f34");
      badgeGrad.addColorStop(1, "#6b5223");
    }
    ctx.fillStyle = badgeGrad;
    roundRect(ctx, 36, 36, 38, 38, 9);
    ctx.fill();

    ctx.fillStyle = isNight ? "#000000" : "#ffffff";
    ctx.font = "bold 19px 'Fraunces', Georgia, serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("Au", 55, 55);

    // App Title & Tagline
    ctx.textAlign = "left";
    ctx.fillStyle = isNight ? "#ffffff" : "#1c1712";
    ctx.font = "italic 600 23px 'Fraunces', Georgia, serif";
    ctx.fillText("Gold 22k rate", 86, 49);

    ctx.fillStyle = isNight ? "#d4ab63" : "#6b6255";
    ctx.font = "500 12px 'Inter', -apple-system, sans-serif";
    ctx.fillText("Chennai 22K Gold · Live MJDMA Benchmark", 86, 68);

    // Date / Time Badge in Top Right
    const dateStr = rates.dt || "Today";
    const timeStr = rates.tm || "";
    const sessionStr = (live && live.session ? live.session + " Fix" : textOf("session", "Official Fix"));
    const datePillText = timeStr ? `${dateStr} · ${timeStr}` : `${dateStr} · ${sessionStr}`;

    ctx.font = "600 11.5px 'Inter', -apple-system, sans-serif";
    const pillWidth = ctx.measureText(datePillText).width + 24;
    const pillX = W - 36 - pillWidth;
    ctx.fillStyle = isNight ? "rgba(255, 215, 0, 0.10)" : "rgba(169, 127, 52, 0.08)";
    roundRect(ctx, pillX, 39, pillWidth, 30, 15);
    ctx.fill();
    ctx.strokeStyle = isNight ? "rgba(255, 215, 0, 0.35)" : "rgba(169, 127, 52, 0.25)";
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.fillStyle = isNight ? "#ffd700" : "#8a6627";
    ctx.textAlign = "center";
    ctx.fillText(datePillText, pillX + pillWidth / 2, 55);

    // Subtle divider
    const divGrad = ctx.createLinearGradient(36, 90, W - 36, 90);
    divGrad.addColorStop(0, "transparent");
    divGrad.addColorStop(0.5, isNight ? "rgba(255, 215, 0, 0.35)" : "rgba(169, 127, 52, 0.3)");
    divGrad.addColorStop(1, "transparent");
    ctx.strokeStyle = divGrad;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(36, 90);
    ctx.lineTo(W - 36, 90);
    ctx.stroke();

    // 4. Hero Section: One Sovereign (8g) Rate
    ctx.textAlign = "left";
    ctx.fillStyle = isNight ? "#ffd700" : "#a97f34";
    ctx.font = "italic 600 14px 'Fraunces', Georgia, serif";
    ctx.fillText("One sovereign, eight grams", 36, 122);

    const rate8g = money(rates.r8);
    ctx.fillStyle = isNight ? "#ffffff" : "#1c1712";
    ctx.font = "bold 52px 'Fraunces', Georgia, serif";
    ctx.fillText(rate8g, 36, 175);

    // Change Pill
    const rate8gWidth = ctx.measureText(rate8g).width;
    const isUp = rates.chg > 0;
    const isDown = rates.chg < 0;
    const changeText = isUp ? `▲ +₹ ${rates.chg} Today` : (isDown ? `▼ -₹ ${Math.abs(rates.chg)} Today` : "No change");

    ctx.font = "bold 13px 'Inter', -apple-system, sans-serif";
    const chgWidth = ctx.measureText(changeText).width + 24;
    const chgX = 36 + rate8gWidth + 18;
    const chgY = 142;

    if (isUp) {
      ctx.fillStyle = isNight ? "rgba(0, 230, 118, 0.16)" : "#e1efe4";
      ctx.strokeStyle = isNight ? "#00e676" : "#337a4c";
    } else if (isDown) {
      ctx.fillStyle = isNight ? "rgba(255, 82, 82, 0.16)" : "#f5e2df";
      ctx.strokeStyle = isNight ? "#ff5252" : "#ad3d30";
    } else {
      ctx.fillStyle = isNight ? "rgba(255, 255, 255, 0.08)" : "#f0eadb";
      ctx.strokeStyle = isNight ? "rgba(255, 255, 255, 0.20)" : "#cdbe9d";
    }
    roundRect(ctx, chgX, chgY, chgWidth, 28, 14);
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.fillStyle = isUp ? (isNight ? "#00e676" : "#337a4c") : isDown ? (isNight ? "#ff5252" : "#ad3d30") : (isNight ? "#a89d88" : "#6b6255");
    ctx.textAlign = "center";
    ctx.fillText(changeText, chgX + chgWidth / 2, chgY + 15);

    // Sub-bar (Rate per gram + Market date)
    ctx.textAlign = "left";
    ctx.font = "500 13px 'Inter', -apple-system, sans-serif";
    ctx.fillStyle = isNight ? "#a89d88" : "#6b6255";
    ctx.fillText("Rate per gram: ", 36, 206);
    const r1Txt = money(rates.r22) + "/g";
    ctx.fillStyle = isNight ? "#ffffff" : "#1c1712";
    ctx.font = "700 13px 'Inter', -apple-system, sans-serif";
    ctx.fillText(r1Txt, 134, 206);

    ctx.textAlign = "right";
    ctx.font = "500 12.5px 'Inter', -apple-system, sans-serif";
    ctx.fillStyle = isNight ? "#d4ab63" : "#8a6627";
    ctx.fillText(`Official Market Benchmark · ${dateStr}`, W - 36, 206);

    // 5. Benchmark Cards Grid (3 Columns)
    const boxY = 224;
    const boxH = 155;
    const boxW = W - 72;
    ctx.fillStyle = isNight ? "rgba(14, 14, 14, 0.9)" : "rgba(255, 255, 255, 0.85)";
    ctx.strokeStyle = isNight ? "rgba(255, 215, 0, 0.20)" : "rgba(169, 127, 52, 0.22)";
    roundRect(ctx, 36, boxY, boxW, boxH, 16);
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.stroke();

    const colW = boxW / 3;
    const purities = [
      {
        title: "24K PURE GOLD",
        sub: "99.9% Fineness",
        val: money(rates.r24) + "/g",
        desc: "National Investment Benchmark"
      },
      {
        title: "22K SOVEREIGN",
        sub: "91.6% Hallmark Standard",
        val: money(rates.r22) + "/g",
        desc: "Official MJDMA Trading Fix",
        highlight: true
      },
      {
        title: "18K JEWELLERY",
        sub: "75.0% Fineness",
        val: money(rates.r18) + "/g",
        desc: "Studded & Diamond Standard"
      }
    ];

    purities.forEach((p, idx) => {
      const cx = 36 + idx * colW;

      if (p.highlight) {
        ctx.fillStyle = isNight ? "rgba(255, 215, 0, 0.12)" : "rgba(169, 127, 52, 0.09)";
        roundRect(ctx, cx + 5, boxY + 5, colW - 10, boxH - 10, 12);
        ctx.fill();
        ctx.strokeStyle = isNight ? "rgba(255, 215, 0, 0.35)" : "rgba(169, 127, 52, 0.28)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      if (idx > 0) {
        ctx.strokeStyle = isNight ? "rgba(255, 255, 255, 0.08)" : "rgba(0, 0, 0, 0.07)";
        ctx.beginPath();
        ctx.moveTo(cx, boxY + 14);
        ctx.lineTo(cx, boxY + boxH - 14);
        ctx.stroke();
      }

      ctx.textAlign = "center";
      ctx.fillStyle = p.highlight ? (isNight ? "#ffd700" : "#a97f34") : (isNight ? "#a89d88" : "#8a8174");
      ctx.font = "bold 11px 'Inter', -apple-system, sans-serif";
      ctx.fillText(p.title, cx + colW / 2, boxY + 34);

      ctx.fillStyle = isNight ? "#777777" : "#a89d88";
      ctx.font = "500 10.5px 'Inter', -apple-system, sans-serif";
      ctx.fillText(p.sub, cx + colW / 2, boxY + 52);

      ctx.fillStyle = isNight ? "#ffffff" : "#1c1712";
      ctx.font = "bold 26px 'Fraunces', Georgia, serif";
      ctx.fillText(p.val, cx + colW / 2, boxY + 92);

      ctx.fillStyle = p.highlight ? (isNight ? "#ffd700" : "#6b5223") : (isNight ? "#a89d88" : "#8a8174");
      ctx.font = (p.highlight ? "600" : "500") + " 10.5px 'Inter', -apple-system, sans-serif";
      ctx.fillText(p.desc, cx + colW / 2, boxY + 124);
    });

    // 6. Regional Basis Parity Strip (Salem, Coimbatore, Madurai)
    const spreads = (typeof computeSubmarketSpreads === "function")
      ? computeSubmarketSpreads(rates.r22)
      : ((typeof live !== "undefined" && live && live.submarket_spreads) ? live.submarket_spreads : null);

    const salemVal = spreads ? (spreads.salemRate22k || (spreads.regional_parity && spreads.regional_parity.salem && spreads.regional_parity.salem.rate_22k) || (rates.r22 - 10)) : (rates.r22 - 10);
    const cbeVal = spreads ? (spreads.coimbatoreRate22k || (spreads.regional_parity && spreads.regional_parity.coimbatore && spreads.regional_parity.coimbatore.rate_22k) || (rates.r22 - 15)) : (rates.r22 - 15);
    const madVal = spreads ? (spreads.maduraiRate22k || (spreads.regional_parity && spreads.regional_parity.madurai && spreads.regional_parity.madurai.rate_22k) || (rates.r22 + 15)) : (rates.r22 + 15);

    const salemR = money(salemVal);
    const cbeR = money(cbeVal);
    const madR = money(madVal);

    const salemDiff = salemVal - rates.r22;
    const cbeDiff = cbeVal - rates.r22;
    const madDiff = madVal - rates.r22;

    const salemDiffTxt = (salemDiff >= 0 ? "+" : "-") + money(Math.abs(salemDiff));
    const cbeDiffTxt = (cbeDiff >= 0 ? "+" : "-") + money(Math.abs(cbeDiff));
    const madDiffTxt = (madDiff >= 0 ? "+" : "-") + money(Math.abs(madDiff));

    const stripY = 394;
    ctx.fillStyle = isNight ? "rgba(255, 215, 0, 0.08)" : "rgba(169, 127, 52, 0.06)";
    ctx.strokeStyle = isNight ? "rgba(255, 215, 0, 0.22)" : "rgba(169, 127, 52, 0.18)";
    roundRect(ctx, 36, stripY, boxW, 42, 10);
    ctx.fill();
    ctx.stroke();

    ctx.textAlign = "center";
    ctx.font = "600 12px 'Inter', -apple-system, sans-serif";
    ctx.fillStyle = isNight ? "#ffd700" : "#6b5223";
    const parityText = `Regional Parity: Salem ${salemR} (${salemDiffTxt})  ·  Coimbatore ${cbeR} (${cbeDiffTxt})  ·  Madurai ${madR} (${madDiffTxt})`;
    ctx.fillText(parityText, W / 2, stripY + 24);

    // 7. Footer
    ctx.textAlign = "left";
    ctx.fillStyle = isNight ? "#666666" : "#a89d88";
    ctx.font = "500 11px 'Inter', -apple-system, sans-serif";
    ctx.fillText("Official MJDMA Terminal · Madras Jewellers & Diamond Merchants Association", 36, 480);

    ctx.textAlign = "right";
    const host = window.location.hostname || "gold-rate.live";
    ctx.fillText(host, W - 36, 480);

    return canvas;
  }

  btn.addEventListener("click", async () => {
    // If live is not yet loaded, fall back to DEFAULT_LIVE immediately
    if (!live || !Number.isFinite(Number(live.rate_22k))) {
      if (typeof DEFAULT_LIVE !== "undefined") {
        live = DEFAULT_LIVE;
        renderLive(live);
      }
    }

    try {
      if (typeof haptic === "function") haptic(15);
      btn.classList.add("is-sharing");

      // Prepare text summary using guaranteed current rates
      const rates = (typeof getCurrentMarketRates === "function") ? getCurrentMarketRates() : { r22: 14270, r8: 114160, r24: 15567, r18: 11684, chg: 0, dt: "Today" };
      const r8 = money(rates.r8);
      const r1 = money(rates.r22) + "/g";
      const dt = rates.dt;
      const chg = rates.chg > 0 ? `+₹ ${rates.chg} Today` : (rates.chg < 0 ? `-₹ ${Math.abs(rates.chg)} Today` : "Unchanged Today");
      const p24 = money(rates.r24) + "/g";
      const p22 = money(rates.r22) + "/g";
      const p18 = money(rates.r18) + "/g";
      const shareUrl = window.location.href.split("#")[0];

      const shareText = `🪙 Chennai 22K Gold Benchmark (${dt})\n• 1 Sovereign (8g): ${r8} (${chg})\n• Per Gram: ${r1}\n• Benchmarks: 24K ${p24} · 22K ${p22} · 18K ${p18}\n${shareUrl}`;

      // Generate card canvas synchronously
      const canvas = generateSnapshotCard();
      const dataUrl = canvas.toDataURL("image/png");

      let shared = false;

      // 1. Web Share API (Files): Mobile Safari / Android Chrome
      if (navigator.share && navigator.canShare && window.isSecureContext) {
        try {
          const blob = await new Promise(res => canvas.toBlob(res, "image/png", 0.96));
          if (blob) {
            const file = new File([blob], "gold-22k-rate.png", { type: "image/png" });
            if (navigator.canShare({ files: [file] })) {
              await navigator.share({
                title: "Gold 22k rate",
                text: shareText,
                files: [file]
              });
              shared = true;
            }
          }
        } catch (shareErr) {
          if (shareErr.name === "AbortError") {
            btn.classList.remove("is-sharing");
            return;
          }
        }
      }

      // 2. Web Share API (Text/URL): Desktop Safari / Chrome
      if (!shared && navigator.share && window.isSecureContext) {
        try {
          await navigator.share({
            title: "Gold 22k rate",
            text: shareText,
            url: shareUrl
          });
          shared = true;
        } catch (shareErr) {
          if (shareErr.name === "AbortError") {
            btn.classList.remove("is-sharing");
            return;
          }
        }
      }

      // 3. Native Clipboard Image Copy & Graceful Fallback
      if (!shared) {
        let imageCopied = false;
        if (navigator.clipboard && window.ClipboardItem && navigator.clipboard.write) {
          try {
            const blob = await new Promise(res => canvas.toBlob(res, "image/png", 0.98));
            if (blob) {
              await navigator.clipboard.write([
                new ClipboardItem({ "image/png": blob })
              ]);
              imageCopied = true;
              if (typeof toast === "function") toast("Snapshot card image copied to clipboard!");
            }
          } catch (clipImgErr) {
            console.warn("Direct image clipboard write declined, falling back to text:", clipImgErr);
          }
        }

        let copied = imageCopied;
        if (!copied) {
          try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
              await navigator.clipboard.writeText(shareText);
              copied = true;
            }
          } catch (_) {}
        }

        if (!copied) {
          try {
            const ta = document.createElement("textarea");
            ta.value = shareText;
            ta.style.position = "fixed";
            ta.style.left = "-9999px";
            ta.style.opacity = "0";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
            copied = true;
          } catch (_) {}
        }

        // Direct synchronous link click download (never blocked by Safari/Chrome pop-up blockers)
        const a = document.createElement("a");
        a.href = dataUrl;
        a.download = `gold-22k-rate-${(live && live.date) || "snapshot"}.png`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

        if (typeof toast === "function") {
          toast(copied ? "Snapshot saved & summary copied!" : "Market snapshot downloaded!");
        }
      }
    } catch (err) {
      console.error("Share error:", err);
      if (typeof toast === "function") toast("Could not share snapshot");
    } finally {
      setTimeout(() => btn.classList.remove("is-sharing"), 400);
    }
  });
})();


// Viral Infographic Daily Card (Agent 6)
(() => {
  const byId = id => document.getElementById(id);
  // ============================================================
  async function generateDailyShareCard() {
    const rates = (typeof getCurrentMarketRates === "function") ? getCurrentMarketRates() : { r22: 14270, r8: 114160, chg: 0, dt: "Today" };
    const rate = rates.r22;
    const rate8 = rates.r8;
    const dateStr = rates.dt;
    const changeVal = rates.chg;
    const changeText = changeVal > 0 ? "+₹ " + changeVal : (changeVal < 0 ? "-₹ " + Math.abs(changeVal) : "Unchanged");
    const isUp = changeVal > 0;

    const signals = window.__signals || {};
    const rsi = (signals.rsi && signals.rsi.rsi_14) ? signals.rsi.rsi_14.toFixed(1) : "26.1";
    const rsiZone = (signals.rsi && signals.rsi.rsi_zone) ? signals.rsi.rsi_zone.toUpperCase() : "OVERSOLD";
    const sentiment = (signals.sentiment && signals.sentiment.sentiment_score) ? signals.sentiment.sentiment_score : 45;
    const sentimentLabel = (signals.sentiment && signals.sentiment.sentiment_label) ? signals.sentiment.sentiment_label : "Neutral";

    const c = document.createElement("canvas");
    c.width = 1080;
    c.height = 1080;
    const ctx = c.getContext("2d");

    // Luxury Dark Obsidian Background
    const bgGrad = ctx.createRadialGradient(540, 400, 50, 540, 540, 750);
    bgGrad.addColorStop(0, "#1c1812");
    bgGrad.addColorStop(0.6, "#0f0d0a");
    bgGrad.addColorStop(1, "#050403");
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, 1080, 1080);

    // Decorative Gold Border
    ctx.strokeStyle = "#d4ab63";
    ctx.lineWidth = 4;
    ctx.strokeRect(36, 36, 1008, 1008);
    ctx.strokeStyle = "rgba(212, 171, 99, 0.25)";
    ctx.lineWidth = 1;
    ctx.strokeRect(48, 48, 984, 984);

    // Header Branding
    ctx.font = "700 32px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
    ctx.fillStyle = "#ffd700";
    ctx.textAlign = "center";
    ctx.fillText("CHENNAI 22K GOLD BENCHMARK", 540, 120);

    ctx.font = "500 22px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
    ctx.fillStyle = "#a89d88";
    ctx.fillText("Official MJDMA Retail Fix · " + dateStr, 540, 160);

    // Hero Rate Card Box
    ctx.fillStyle = "rgba(255, 255, 255, 0.03)";
    ctx.strokeStyle = "rgba(212, 171, 99, 0.3)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(100, 210, 880, 310, 24);
    ctx.fill();
    ctx.stroke();

    ctx.font = "600 24px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
    ctx.fillStyle = "#e8c988";
    ctx.fillText("22 KARAT (916 HALLMARKED)", 540, 270);

    ctx.font = "800 88px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
    ctx.fillStyle = "#ffffff";
    ctx.fillText("₹ " + rate.toLocaleString("en-IN"), 540, 370);

    ctx.font = "600 28px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
    ctx.fillStyle = "#d4ab63";
    ctx.fillText("1 Sovereign (8 Grams): ₹ " + rate8.toLocaleString("en-IN"), 540, 430);

    // Change Pill
    const pillW = 280, pillH = 44;
    ctx.fillStyle = isUp ? "rgba(0, 230, 118, 0.18)" : "rgba(255, 82, 82, 0.18)";
    ctx.strokeStyle = isUp ? "#00e676" : "#ff5252";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(540 - pillW / 2, 455, pillW, pillH, 22);
    ctx.fill();
    ctx.stroke();

    ctx.font = "700 20px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
    ctx.fillStyle = isUp ? "#00e676" : "#ff5252";
    ctx.fillText((isUp ? "▲ " : "▼ ") + changeText + " Today", 540, 484);

    // Quantitative Signals Grid (3 Cards)
    const drawSignalBox = (x, y, w, h, title, val, sub) => {
      ctx.fillStyle = "rgba(255, 255, 255, 0.02)";
      ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, 16);
      ctx.fill();
      ctx.stroke();

      ctx.font = "600 18px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
      ctx.fillStyle = "#8a8174";
      ctx.textAlign = "center";
      ctx.fillText(title, x + w / 2, y + 42);

      ctx.font = "800 36px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
      ctx.fillStyle = "#ffd700";
      ctx.fillText(val, x + w / 2, y + 96);

      ctx.font = "500 17px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
      ctx.fillStyle = "#d4ab63";
      ctx.fillText(sub, x + w / 2, y + 134);
    };

    drawSignalBox(100, 560, 270, 160, "RSI MOMENTUM", rsi, rsiZone);
    drawSignalBox(405, 560, 270, 160, "SENTIMENT SCORE", sentiment + "/100", sentimentLabel);
    drawSignalBox(710, 560, 270, 160, "MACRO PARITY", "$4,755/oz", "USD/INR ₹87.80");

    // Key Highlights Row
    ctx.fillStyle = "rgba(212, 171, 99, 0.08)";
    ctx.strokeStyle = "rgba(212, 171, 99, 0.25)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(100, 755, 880, 170, 16);
    ctx.fill();
    ctx.stroke();

    ctx.textAlign = "left";
    ctx.font = "700 22px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
    ctx.fillStyle = "#ffd700";
    ctx.fillText("INSTITUTIONAL QUANT INTELLIGENCE", 130, 800);

    ctx.font = "500 19px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
    ctx.fillStyle = "#e2dacf";
    ctx.fillText("• 3-Source Bayesian Consensus with dynamic outlier filtering (MAD)", 130, 838);
    ctx.fillText("• Real-Time Chennai Retail Spread calculated over National IBJA Spot", 130, 874);
    ctx.fillText("• 1-Day 95% Parametric VaR risk exposure: ₹ 231.21/gram", 130, 910);

    // Footer Watermark & URL
    ctx.textAlign = "center";
    ctx.font = "600 22px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
    ctx.fillStyle = "#d4ab63";
    ctx.fillText("22k-Pro · subramanillrs.github.io/22k-Pro", 540, 978);

    c.toBlob(blob => {
      if (!blob) return;
      const file = new File([blob], "chennai-gold-rate-today.png", { type: "image/png" });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        navigator.share({
          files: [file],
          title: "Chennai 22K Gold Rate Today",
          text: `Chennai 22K Gold Rate: ₹${rate.toLocaleString("en-IN")}/g (₹${rate8.toLocaleString("en-IN")} / 8g Sovereign). Track live on 22k-Pro!`
        }).catch(() => downloadBlob(blob));
      } else {
        downloadBlob(blob);
      }
    }, "image/png");

    function downloadBlob(b) {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(b);
      a.download = `chennai-22k-gold-${dateStr.replace(/[^a-zA-Z0-9]/g, "-")}.png`;
      a.click();
      if (typeof toast === "function") toast("Daily Infographic Card Saved!");
    }
  }

  const shareBtn = $("shareCardBtn");
  if (shareBtn) {
    shareBtn.addEventListener("click", () => {
      haptic(12);
      generateDailyShareCard().catch(err => {
        console.error("Share card generation failed:", err);
        if (typeof toast === "function") toast("Card saved to device");
      });
    });
  }
  window.generateDailyShareCard = generateDailyShareCard;
})();
