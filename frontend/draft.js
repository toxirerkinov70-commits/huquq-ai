/* Drafted documents and slides: shown in the chat, taken away as PDF or PNG.

   Both exports are done here rather than on the server. A PDF is the browser's own
   print pipeline, which produces real selectable text and costs nothing to run. A PNG
   is drawn onto a canvas by hand — no library is loaded, because the page may not fetch
   anything from another host, and a hand-drawn canvas also lets the letter keep the
   margins and the type an office expects. */

(function () {
  const INK = "#201E1D";
  const PAPER = "#ffffff";
  const ACCENT = "#0088B0";
  const MUTED = "#6b6764";

  const SERIF = '"Source Serif 4", "Source Serif Pro", Georgia, "Times New Roman", serif';
  const SANS = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

  /* ---------- shared drawing helpers ---------- */

  function wrapText(ctx, text, maxWidth) {
    const lines = [];
    for (const paragraph of String(text).split("\n")) {
      const words = paragraph.split(/\s+/).filter(Boolean);
      if (!words.length) {
        lines.push("");
        continue;
      }
      let line = words[0];
      for (let i = 1; i < words.length; i += 1) {
        const candidate = `${line} ${words[i]}`;
        if (ctx.measureText(candidate).width > maxWidth) {
          lines.push(line);
          line = words[i];
        } else {
          line = candidate;
        }
      }
      lines.push(line);
    }
    return lines;
  }

  function download(canvas, name) {
    canvas.toBlob((blob) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      link.click();
      // revoking immediately cancels the download in Firefox
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    }, "image/png");
  }

  /* ---------- the letter ---------- */

  const PAGE_W = 1240;
  const PAGE_MIN_H = 1754; // A4 at 150 dpi, so a short letter still looks like a page
  const MARGIN = 110;

  /* Laid out twice: once to measure, once to draw. The height is only known after the
     text has been wrapped, and a letter that runs long should grow rather than clip. */
  function layoutDocument(doc, ctx, draw) {
    const width = PAGE_W - MARGIN * 2;
    let y = MARGIN;

    const line = (text, { font, size, colour, align, indent, gap, maxWidth }) => {
      ctx.font = `${font || ""} ${size}px ${SANS}`.trim();
      ctx.fillStyle = colour || INK;
      const limit = maxWidth || width;
      const lines = wrapText(ctx, text, limit - (indent || 0));
      for (let i = 0; i < lines.length; i += 1) {
        if (draw) {
          const x =
            align === "right"
              ? PAGE_W - MARGIN - ctx.measureText(lines[i]).width
              : align === "center"
                ? (PAGE_W - ctx.measureText(lines[i]).width) / 2
                : MARGIN + (i === 0 ? indent || 0 : 0);
          ctx.fillText(lines[i], x, y);
        }
        y += size * 1.45;
      }
      y += gap || 0;
    };

    if (doc.recipient) {
      line(doc.recipient, { size: 24, align: "right", maxWidth: width * 0.55 });
      y += 6;
    }
    if (doc.sender) {
      line(doc.sender, { size: 24, align: "right", colour: MUTED, maxWidth: width * 0.55 });
    }
    y += 54;

    ctx.font = `700 40px ${SERIF}`;
    if (draw) {
      ctx.fillStyle = INK;
      const w = ctx.measureText(doc.title).width;
      ctx.fillText(doc.title, (PAGE_W - w) / 2, y);
    }
    // the baseline is the top of the glyphs, so the rule clears the title's own height
    y += 56;
    if (draw) {
      ctx.fillStyle = ACCENT;
      ctx.fillRect((PAGE_W - 90) / 2, y, 90, 3);
    }
    y += 54;

    for (const paragraph of doc.body || []) {
      line(paragraph, { size: 25, indent: 48, gap: 18 });
    }

    if ((doc.requests || []).length) {
      y += 14;
      line("So'rayman:", { font: "600", size: 25, gap: 10 });
      doc.requests.forEach((item, index) => {
        line(`${index + 1}. ${item}`, { size: 25, indent: 28, gap: 8 });
      });
    }

    if ((doc.grounds || []).length) {
      y += 14;
      line(`Huquqiy asos: ${doc.grounds.join("; ")}`, { size: 23, colour: MUTED, gap: 6 });
    }

    if ((doc.attachments || []).length) {
      y += 10;
      line("Ilova:", { font: "600", size: 23, gap: 6 });
      doc.attachments.forEach((item, index) => {
        line(`${index + 1}. ${item}`, { size: 23, colour: MUTED, gap: 4 });
      });
    }

    y += 70;
    if (draw) {
      ctx.font = `25px ${SANS}`;
      ctx.fillStyle = INK;
      ctx.fillText("[sana]", MARGIN, y);
      const sign = "[imzo] / [F.I.Sh.]";
      ctx.fillText(sign, PAGE_W - MARGIN - ctx.measureText(sign).width, y);
    }
    y += 60;

    line(doc.disclaimer || "", { size: 19, colour: MUTED });
    return y + MARGIN;
  }

  function documentCanvas(doc) {
    const measure = document.createElement("canvas").getContext("2d");
    measure.canvas.width = PAGE_W;
    const height = Math.max(PAGE_MIN_H, Math.ceil(layoutDocument(doc, measure, false)));

    const canvas = document.createElement("canvas");
    canvas.width = PAGE_W;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = PAPER;
    ctx.fillRect(0, 0, PAGE_W, height);
    ctx.textBaseline = "top";
    layoutDocument(doc, ctx, true);
    return canvas;
  }

  /* ---------- slides ---------- */

  const SLIDE_W = 1600;
  const SLIDE_H = 900;

  function slideCanvas(slide, index, total, deckTitle) {
    const canvas = document.createElement("canvas");
    canvas.width = SLIDE_W;
    canvas.height = SLIDE_H;
    const ctx = canvas.getContext("2d");
    ctx.textBaseline = "top";

    ctx.fillStyle = INK;
    ctx.fillRect(0, 0, SLIDE_W, SLIDE_H);
    ctx.fillStyle = ACCENT;
    ctx.fillRect(0, 0, 10, SLIDE_H);

    // the mark, drawn from the same geometry as the logo
    ctx.save();
    ctx.translate(SLIDE_W - 150, 70);
    ctx.scale(0.85, 0.85);
    ctx.strokeStyle = "#F3F2F2";
    ctx.lineWidth = 5.5;
    ctx.lineJoin = "miter";
    ctx.beginPath();
    ctx.moveTo(20, 8); ctx.lineTo(8, 8); ctx.lineTo(8, 56); ctx.lineTo(20, 56);
    ctx.moveTo(44, 8); ctx.lineTo(56, 8); ctx.lineTo(56, 56); ctx.lineTo(44, 56);
    ctx.moveTo(30, 26); ctx.lineTo(66 - 20, 26);
    ctx.stroke();
    ctx.strokeStyle = "#62C5EE";
    ctx.beginPath();
    ctx.moveTo(30, 39); ctx.lineTo(43, 39);
    ctx.stroke();
    ctx.restore();

    const margin = 110;
    const width = SLIDE_W - margin * 2 - 120;
    let y = 190;

    ctx.font = `700 62px ${SERIF}`;
    ctx.fillStyle = "#F3F2F2";
    for (const piece of wrapText(ctx, slide.title || deckTitle || "", width)) {
      ctx.fillText(piece, margin, y);
      y += 74;
    }

    y += 34;
    ctx.font = `34px ${SANS}`;
    for (const bullet of slide.bullets || []) {
      ctx.fillStyle = ACCENT;
      ctx.fillRect(margin, y + 16, 22, 4);
      ctx.fillStyle = "#DAD7D4";
      for (const piece of wrapText(ctx, bullet, width - 54)) {
        ctx.fillText(piece, margin + 54, y);
        y += 48;
      }
      y += 18;
    }

    if (slide.grounds) {
      ctx.font = `26px ${SANS}`;
      ctx.fillStyle = "#8C8783";
      ctx.fillText(slide.grounds, margin, SLIDE_H - 130);
    }
    ctx.font = `24px ${SANS}`;
    ctx.fillStyle = "#6E6A67";
    ctx.fillText(`${index + 1} / ${total}`, margin, SLIDE_H - 80);
    return canvas;
  }

  /* ---------- print ---------- */

  function printable(node, title) {
    const frame = document.createElement("iframe");
    frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
    document.body.appendChild(frame);
    const doc = frame.contentDocument;
    doc.open();
    doc.write(
      `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title>` +
        `<style>${PRINT_CSS}</style></head><body>${node}</body></html>`
    );
    doc.close();
    frame.contentWindow.focus();
    // the images inside need a tick to lay out before the dialog measures pages
    setTimeout(() => {
      frame.contentWindow.print();
      setTimeout(() => frame.remove(), 1000);
    }, 250);
  }

  const PRINT_CSS = `
    @page { size: A4; margin: 18mm 16mm; }
    body { font: 12pt/1.6 ${SANS}; color: ${INK}; margin: 0; }
    .to { text-align: right; margin-bottom: 4mm; white-space: pre-line; }
    .from { text-align: right; color: ${MUTED}; margin-bottom: 12mm; white-space: pre-line; }
    h1 { font: 700 20pt/1.2 ${SERIF}; text-align: center; margin: 0 0 3mm; letter-spacing: .04em; }
    .rule { width: 22mm; height: 1mm; background: ${ACCENT}; margin: 0 auto 9mm; }
    p { margin: 0 0 3mm; text-indent: 8mm; text-align: justify; }
    h2 { font-size: 12pt; margin: 6mm 0 2mm; }
    ol { margin: 0 0 3mm; padding-left: 8mm; }
    li { margin-bottom: 1.5mm; }
    .grounds, .note { color: ${MUTED}; font-size: 10pt; }
    .sign { display: flex; justify-content: space-between; margin-top: 14mm; }
    .note { margin-top: 10mm; }
    .slide { page-break-after: always; background: ${INK}; color: #F3F2F2;
             padding: 18mm; height: 160mm; }
    .slide h3 { font: 700 20pt/1.25 ${SERIF}; margin: 0 0 8mm; }
    .slide li { margin-bottom: 4mm; font-size: 13pt; }
    .slide .grounds { color: #8C8783; }
  `;

  function escapeHtml(value) {
    return String(value).replace(
      /[&<>"]/g,
      (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]
    );
  }

  function documentHtml(doc) {
    const parts = [];
    if (doc.recipient) parts.push(`<div class="to">${escapeHtml(doc.recipient)}</div>`);
    if (doc.sender) parts.push(`<div class="from">${escapeHtml(doc.sender)}</div>`);
    parts.push(`<h1>${escapeHtml(doc.title)}</h1><div class="rule"></div>`);
    for (const paragraph of doc.body || []) parts.push(`<p>${escapeHtml(paragraph)}</p>`);
    if ((doc.requests || []).length) {
      parts.push("<h2>So'rayman:</h2><ol>");
      for (const item of doc.requests) parts.push(`<li>${escapeHtml(item)}</li>`);
      parts.push("</ol>");
    }
    if ((doc.grounds || []).length) {
      parts.push(`<div class="grounds">Huquqiy asos: ${escapeHtml(doc.grounds.join("; "))}</div>`);
    }
    if ((doc.attachments || []).length) {
      parts.push("<h2>Ilova:</h2><ol>");
      for (const item of doc.attachments) parts.push(`<li>${escapeHtml(item)}</li>`);
      parts.push("</ol>");
    }
    parts.push('<div class="sign"><span>[sana]</span><span>[imzo] / [F.I.Sh.]</span></div>');
    parts.push(`<div class="note">${escapeHtml(doc.disclaimer || "")}</div>`);
    return parts.join("");
  }

  function slidesHtml(deck) {
    return (deck.slides || [])
      .map((slide) => {
        const bullets = (slide.bullets || [])
          .map((b) => `<li>${escapeHtml(b)}</li>`)
          .join("");
        const grounds = slide.grounds
          ? `<div class="grounds">${escapeHtml(slide.grounds)}</div>`
          : "";
        return `<section class="slide"><h3>${escapeHtml(
          slide.title || deck.title || ""
        )}</h3><ul>${bullets}</ul>${grounds}</section>`;
      })
      .join("");
  }

  /* ---------- what the chat shows ---------- */

  function preview(doc) {
    const box = el("div", "draft");
    const head = el("div", "draft-head");
    head.appendChild(el("span", "draft-kind", doc.kind === "slayd" ? "Taqdimot" : "Hujjat loyihasi"));
    const actions = el("div", "draft-actions");

    const pdf = el("button", "draft-btn", "PDF");
    pdf.type = "button";
    pdf.addEventListener("click", () => {
      printable(doc.kind === "slayd" ? slidesHtml(doc) : documentHtml(doc), doc.title || "Hujjat");
    });

    const png = el("button", "draft-btn", "PNG");
    png.type = "button";
    png.addEventListener("click", () => {
      if (doc.kind === "slayd") {
        (doc.slides || []).forEach((slide, index) => {
          setTimeout(() => {
            download(
              slideCanvas(slide, index, doc.slides.length, doc.title),
              `slayd-${index + 1}.png`
            );
          }, index * 350);
        });
      } else {
        download(documentCanvas(doc), `${doc.doc_type || "hujjat"}.png`);
      }
    });

    actions.appendChild(pdf);
    actions.appendChild(png);
    head.appendChild(actions);
    box.appendChild(head);

    const sheet = el("div", doc.kind === "slayd" ? "draft-deck" : "draft-sheet");
    if (doc.kind === "slayd") {
      (doc.slides || []).forEach((slide, index) => {
        const card = el("div", "draft-slide");
        card.appendChild(el("h4", null, slide.title || doc.title || ""));
        const list = el("ul");
        for (const bullet of slide.bullets || []) list.appendChild(el("li", null, bullet));
        card.appendChild(list);
        if (slide.grounds) card.appendChild(el("div", "draft-grounds", slide.grounds));
        card.appendChild(el("div", "draft-page", `${index + 1} / ${doc.slides.length}`));
        sheet.appendChild(card);
      });
    } else {
      if (doc.recipient) sheet.appendChild(el("div", "draft-to", doc.recipient));
      if (doc.sender) sheet.appendChild(el("div", "draft-from", doc.sender));
      sheet.appendChild(el("h4", "draft-title", doc.title));
      for (const paragraph of doc.body || []) sheet.appendChild(el("p", null, paragraph));
      if ((doc.requests || []).length) {
        sheet.appendChild(el("h5", null, "So'rayman:"));
        const list = el("ol");
        for (const item of doc.requests) list.appendChild(el("li", null, item));
        sheet.appendChild(list);
      }
      if ((doc.grounds || []).length) {
        sheet.appendChild(el("div", "draft-grounds", `Huquqiy asos: ${doc.grounds.join("; ")}`));
      }
      if ((doc.attachments || []).length) {
        sheet.appendChild(el("h5", null, "Ilova:"));
        const list = el("ol");
        for (const item of doc.attachments) list.appendChild(el("li", null, item));
        sheet.appendChild(list);
      }
    }
    box.appendChild(sheet);
    box.appendChild(el("div", "draft-note", doc.disclaimer || ""));
    return box;
  }

  // the canvases are exported too: they are what the download produces, so a check
  // that renders one is checking the file the user gets
  window.HuquqDraft = { preview, documentCanvas, slideCanvas };
})();
