import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const pptxgen = require("pptxgenjs");

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  throw new Error("usage: node render_pptx.mjs <input.json> <output.pptx>");
}

const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
const deck = new pptxgen();
deck.layout = "LAYOUT_WIDE";
deck.author = "高校思政课 AI 智能教学辅助平台";
deck.subject = payload.chapter_title || "高校思政课教学课件";
deck.title = payload.ppt?.title || payload.chapter_title || "教学课件";
deck.company = "高校思政课 AI 智能教学辅助平台";
deck.lang = "zh-CN";
deck.theme = {
  headFontFace: payload.ppt?.design?.fonts?.heading || "Microsoft YaHei",
  bodyFontFace: payload.ppt?.design?.fonts?.body || "Microsoft YaHei",
  lang: "zh-CN",
};

const C = {
  red: "9E2335",
  redDark: "681827",
  redSoft: "F8EDEF",
  blue: "2459B8",
  blueDark: "173B72",
  blueSoft: "EEF3FC",
  gold: "D3A23A",
  goldSoft: "F8F0DD",
  ink: "172033",
  body: "3D4960",
  muted: "758198",
  line: "D9E0EA",
  paper: "F7F6F2",
  white: "FFFFFF",
};

const cleanArray = (value, maximum = 5) =>
  (Array.isArray(value) ? value : []).filter(Boolean).slice(0, maximum).map(String);

const designPalette = {
  background: payload.ppt?.design?.palette?.background || C.paper,
  surface: payload.ppt?.design?.palette?.surface || C.white,
  primary: payload.ppt?.design?.palette?.primary || C.red,
  secondary: payload.ppt?.design?.palette?.secondary || C.blue,
  accent: payload.ppt?.design?.palette?.accent || C.gold,
  text: payload.ppt?.design?.palette?.text || C.ink,
  muted: payload.ppt?.design?.palette?.muted || C.muted,
  inverse: payload.ppt?.design?.palette?.inverse || C.white,
};
const designFonts = {
  heading: payload.ppt?.design?.fonts?.heading || "Microsoft YaHei",
  body: payload.ppt?.design?.fonts?.body || "Microsoft YaHei",
};

const textStyles = {
  hero: { fontSize: 46, bold: true },
  title: { fontSize: 31, bold: true },
  subtitle: { fontSize: 22, bold: true },
  body: { fontSize: 18, bold: false },
  label: { fontSize: 12, bold: true, charSpacing: 1.4 },
  number: { fontSize: 42, bold: true, fontFace: "Aptos" },
  quote: { fontSize: 25, bold: true, italic: false },
};

function resolveCanvasSource(data, source, index) {
  if (source === "title") return data.title || "";
  if (source === "takeaway") return data.takeaway || "";
  if (source === "keyword") return data.keyword || "";
  if (source === "page_number") return String(index).padStart(2, "0");
  let match = source.match(/^bullet:(\d+)$/);
  if (match) return data.bullets?.[Number(match[1])] || "";
  match = source.match(/^(left|right)\.title$/);
  if (match) return data[match[1]]?.title || "";
  match = source.match(/^(left|right)\.point:(\d+)$/);
  if (match) return data[match[1]]?.points?.[Number(match[2])] || "";
  match = source.match(/^step:(\d+)\.(title|description)$/);
  if (match) return data.steps?.[Number(match[1])]?.[match[2]] || "";
  match = source.match(/^timeline:(\d+)\.(label|title)$/);
  if (match) return data.timeline?.[Number(match[1])]?.[match[2]] || "";
  return "";
}

function canvasBox(element) {
  return {
    x: Number(element.x || 0) * 0.13333,
    y: Number(element.y || 0) * 0.075,
    w: Number(element.w || 1) * 0.13333,
    h: Number(element.h || 1) * 0.075,
  };
}

function canvasShape(shape) {
  return {
    rect: deck.ShapeType.rect,
    roundRect: deck.ShapeType.roundRect,
    ellipse: deck.ShapeType.ellipse,
    arc: deck.ShapeType.arc,
  }[shape] || deck.ShapeType.rect;
}

function addCanvasSlide(data, index) {
  const slide = deck.addSlide();
  const elements = Array.isArray(data.canvas) ? data.canvas : [];
  const backgroundRole = data.canvas_background || elements[0]?.background || "background";
  slide.background = { color: designPalette[backgroundRole] || designPalette.background };
  elements.forEach((element) => {
    const box = canvasBox(element);
    const color = designPalette[element.color] || designPalette.text;
    const fill = element.fill ? designPalette[element.fill] : null;
    if (element.type === "image") {
      const storagePath = data.visual_asset?.storage_path;
      if (!storagePath || !payload.artifact_root) return;
      const root = path.resolve(payload.artifact_root);
      const imagePath = path.resolve(root, storagePath);
      if (imagePath !== root && !imagePath.startsWith(`${root}${path.sep}`)) return;
      slide.addImage({ path: imagePath, ...box });
      return;
    }
    if (element.type === "line") {
      slide.addShape(deck.ShapeType.line, {
        ...box,
        line: { color, width: element.bold ? 2.5 : 1.2 },
      });
      return;
    }
    if (element.type === "shape") {
      slide.addShape(canvasShape(element.shape), {
        ...box,
        line: { color, transparency: fill ? 100 : 0, width: 1.2 },
        fill: fill ? { color: fill } : { color, transparency: 100 },
      });
      return;
    }
    const text = resolveCanvasSource(data, element.source || "", index);
    if (!text) return;
    if (fill) {
      slide.addShape(canvasShape(element.shape === "rect" ? "roundRect" : element.shape), {
        ...box,
        line: { color: fill, transparency: 100 },
        fill: { color: fill },
      });
    }
    const style = textStyles[element.style] || textStyles.body;
    slide.addText(text, {
      ...box,
      fontFace: style.fontFace || (
        ["hero", "title", "subtitle", "quote"].includes(element.style)
          ? designFonts.heading
          : designFonts.body
      ),
      fontSize: style.fontSize,
      bold: element.bold || style.bold,
      italic: style.italic || false,
      charSpacing: style.charSpacing || 0,
      color,
      align: element.align || "left",
      valign: "mid",
      margin: fill ? 0.12 : 0,
      fit: "shrink",
      breakLine: false,
    });
  });
  addNotes(slide, data);
}

function addFooter(slide, index, dark = false) {
  const color = dark ? "E8EDF6" : C.muted;
  slide.addText(payload.chapter_title || payload.course_name || "高校思政课", {
    x: 0.72, y: 7.1, w: 6.4, h: 0.2,
    fontSize: 9, color, margin: 0, breakLine: false,
  });
  slide.addText(String(index).padStart(2, "0"), {
    x: 12.08, y: 7.04, w: 0.55, h: 0.22,
    fontFace: "Aptos", fontSize: 9, color,
    align: "right", margin: 0,
  });
}

function addLightBase(slide, index) {
  slide.background = { color: C.paper };
  slide.addShape(deck.ShapeType.rect, {
    x: 0, y: 0, w: 0.12, h: 7.5,
    line: { color: C.red, transparency: 100 },
    fill: { color: C.red },
  });
  addFooter(slide, index);
}

function addHeading(slide, data, index, eyebrow = "专题学习") {
  addLightBase(slide, index);
  slide.addText(eyebrow, {
    x: 0.72, y: 0.42, w: 2.4, h: 0.24,
    fontSize: 11, bold: true, color: C.blue,
    charSpacing: 1.8, margin: 0,
  });
  slide.addText(data.title || "教学内容", {
    x: 0.72, y: 0.76, w: 11.75, h: 0.58,
    fontSize: 35, bold: true, color: C.ink,
    margin: 0, fit: "shrink", breakLine: false,
  });
  slide.addShape(deck.ShapeType.line, {
    x: 0.72, y: 1.52, w: 11.88, h: 0,
    line: { color: C.line, width: 1 },
  });
}

function addNotes(slide, slideData) {
  const refs = slideData.evidence_refs || [];
  const sourceLines = refs.map((ref) => {
    const match = String(ref).match(/资料(\d+)/);
    const item = match ? payload.evidence?.[Number(match[1]) - 1] : null;
    if (!item) return `[${ref}] 已确认证据快照`;
    return `[${ref}] ${item.source_title || "课程资料"}；${item.position || ""}`;
  });
  slide.addNotes([
    slideData.speaker_notes || "",
    "",
    "[Sources]",
    ...(sourceLines.length ? sourceLines : ["本页无外部非平凡事实引用"]),
    "[/Sources]",
  ].join("\n"));
}

function addBulletList(slide, bullets, box, options = {}) {
  const items = cleanArray(bullets, options.maximum || 5);
  if (!items.length) return;
  const runs = items.map((text) => ({
    text,
    options: {
      bullet: options.numbered ? { type: "number" } : { indent: 18 },
      hanging: 4,
      breakLine: true,
    },
  }));
  slide.addText(runs, {
    ...box,
    fontSize: options.fontSize || 19,
    color: options.color || C.body,
    paraSpaceAfterPt: options.paraSpaceAfterPt || 14,
    margin: 0.04,
    valign: "top",
    fit: "shrink",
  });
}

function addTitleSlide(data, index) {
  const slide = deck.addSlide();
  slide.background = { color: C.redDark };
  slide.addShape(deck.ShapeType.rect, {
    x: 8.62, y: 0, w: 4.72, h: 7.5,
    line: { color: C.blueDark, transparency: 100 },
    fill: { color: C.blueDark },
  });
  slide.addShape(deck.ShapeType.arc, {
    x: 9.35, y: 1.08, w: 3.35, h: 3.35,
    adjustPoint: 0.2,
    rotate: 18,
    line: { color: "6E8FC8", transparency: 18, width: 2 },
    fill: { color: C.blueDark, transparency: 100 },
  });
  slide.addShape(deck.ShapeType.line, {
    x: 0.82, y: 1.08, w: 1.25, h: 0,
    line: { color: C.gold, width: 3 },
  });
  slide.addText(payload.course_name || "高校思政课", {
    x: 0.82, y: 1.34, w: 7.2, h: 0.36,
    fontSize: 18, bold: true, color: "F0D691", margin: 0,
  });
  slide.addText(data.title || payload.ppt?.title || payload.chapter_title, {
    x: 0.82, y: 2.0, w: 7.3, h: 2.05,
    fontSize: 50, bold: true, color: C.white,
    valign: "mid", margin: 0, fit: "shrink",
  });
  slide.addText(data.takeaway || payload.ppt?.subtitle || payload.chapter_title, {
    x: 0.84, y: 4.48, w: 7.05, h: 0.82,
    fontSize: 20, color: "E8EDF6", margin: 0, fit: "shrink",
  });
  slide.addText("思想 · 理论 · 实践", {
    x: 9.22, y: 5.22, w: 3.45, h: 0.4,
    fontSize: 16, bold: true, color: C.white, align: "center", margin: 0,
  });
  slide.addText("教学草稿 · 请教师核验后使用", {
    x: 9.28, y: 5.78, w: 3.32, h: 0.3,
    fontSize: 11, color: "CBD7EA", align: "center", margin: 0,
  });
  slide.addText(String(index).padStart(2, "0"), {
    x: 11.15, y: 0.76, w: 1.1, h: 0.7,
    fontFace: "Aptos", fontSize: 32, bold: true,
    color: "7797CC", align: "right", margin: 0,
  });
  addNotes(slide, data);
}

function addAgendaSlide(data, index) {
  const slide = deck.addSlide();
  addHeading(slide, data, index, "学习路径");
  const bullets = cleanArray(data.bullets, 5);
  const count = Math.max(bullets.length, 1);
  const width = 11.3 / count;
  slide.addText(data.takeaway || "", {
    x: 0.74, y: 1.78, w: 10.6, h: 0.48,
    fontSize: 22, bold: true, color: C.red, margin: 0,
  });
  bullets.forEach((text, itemIndex) => {
    const x = 0.74 + itemIndex * width;
    if (itemIndex > 0) {
      slide.addShape(deck.ShapeType.line, {
        x: x - 0.18, y: 2.78, w: 0, h: 2.25,
        line: { color: C.line, width: 1 },
      });
    }
    slide.addText(String(itemIndex + 1).padStart(2, "0"), {
      x, y: 2.62, w: width - 0.35, h: 0.78,
      fontFace: "Aptos", fontSize: 34, bold: true, color: C.gold, margin: 0,
    });
    slide.addText(text, {
      x, y: 3.58, w: width - 0.42, h: 1.28,
      fontSize: 22, bold: true, color: C.ink,
      margin: 0, fit: "shrink", valign: "top",
    });
  });
  addNotes(slide, data);
}

function addQuestionSlide(data, index) {
  const slide = deck.addSlide();
  slide.background = { color: C.blueDark };
  slide.addShape(deck.ShapeType.rect, {
    x: 0, y: 0, w: 0.14, h: 7.5,
    line: { color: C.gold, transparency: 100 },
    fill: { color: C.gold },
  });
  slide.addText("?", {
    x: 0.75, y: 0.72, w: 2.35, h: 2.15,
    fontFace: "Georgia", fontSize: 118, bold: true,
    color: "5677AA", margin: 0, align: "center",
  });
  slide.addText("问题导入", {
    x: 3.42, y: 0.82, w: 2.2, h: 0.28,
    fontSize: 12, bold: true, color: "AFC4E8",
    charSpacing: 2, margin: 0,
  });
  slide.addText(data.title || "从问题开始", {
    x: 3.38, y: 1.34, w: 8.75, h: 1.42,
    fontSize: 38, bold: true, color: C.white,
    margin: 0, fit: "shrink", valign: "mid",
  });
  slide.addText(data.takeaway || "", {
    x: 3.4, y: 3.05, w: 8.55, h: 0.85,
    fontSize: 23, color: "E4EBF7", margin: 0, fit: "shrink",
  });
  addBulletList(slide, data.bullets, {
    x: 3.58, y: 4.22, w: 8.2, h: 1.68,
  }, { fontSize: 17, color: "D2DDEF", maximum: 3, paraSpaceAfterPt: 9 });
  addFooter(slide, index, true);
  addNotes(slide, data);
}

function addContentSlide(data, index) {
  const slide = deck.addSlide();
  addHeading(slide, data, index, "核心内容");
  slide.addText(data.takeaway || "", {
    x: 0.74, y: 1.82, w: 8.75, h: 0.78,
    fontSize: 25, bold: true, color: C.red,
    margin: 0, fit: "shrink",
  });
  slide.addText(String(index).padStart(2, "0"), {
    x: 10.02, y: 1.62, w: 2.15, h: 1.28,
    fontFace: "Aptos", fontSize: 70, bold: true,
    color: "E3D7C2", align: "right", margin: 0,
  });
  slide.addShape(deck.ShapeType.line, {
    x: 0.76, y: 2.86, w: 0.92, h: 0,
    line: { color: C.gold, width: 4 },
  });
  addBulletList(slide, data.bullets, {
    x: 0.9, y: 3.18, w: 10.85, h: 2.72,
  }, { fontSize: 20 });
  addNotes(slide, data);
}

function addConceptSlide(data, index) {
  const slide = deck.addSlide();
  addHeading(slide, data, index, "核心概念");
  const bullets = cleanArray(data.bullets, 4);
  if (bullets.length <= 2) {
    slide.addShape(deck.ShapeType.line, {
      x: 5.18, y: 2.12, w: 0, h: 3.38,
      line: { color: C.gold, width: 2.5 },
    });
    slide.addText(data.keyword || "核心概念", {
      x: 0.92, y: 2.5, w: 3.62, h: 1.3,
      fontSize: 38, bold: true, color: C.red,
      margin: 0, fit: "shrink", valign: "mid",
    });
    slide.addText(data.takeaway || "", {
      x: 0.94, y: 4.18, w: 3.55, h: 0.95,
      fontSize: 20, bold: true, color: C.blue,
      margin: 0, fit: "shrink",
    });
    addBulletList(slide, bullets, {
      x: 5.82, y: 2.48, w: 5.68, h: 2.42,
    }, { fontSize: 22, maximum: 2, paraSpaceAfterPt: 20 });
    addNotes(slide, data);
    return;
  }
  const centerX = 5.15;
  const centerY = 2.55;
  const positions = [
    { x: 0.85, y: 2.15, w: 3.05, h: 1.15 },
    { x: 9.15, y: 2.15, w: 3.05, h: 1.15 },
    { x: 0.85, y: 4.5, w: 3.05, h: 1.15 },
    { x: 9.15, y: 4.5, w: 3.05, h: 1.15 },
  ];
  positions.slice(0, bullets.length).forEach((position) => {
    const targetX = position.x < centerX ? position.x + position.w : position.x;
    const targetY = position.y + position.h / 2;
    slide.addShape(deck.ShapeType.line, {
      x: position.x < centerX ? targetX : 7.85,
      y: targetY,
      w: position.x < centerX ? centerX - targetX : targetX - 7.85,
      h: centerY + 1.05 - targetY,
      line: { color: "B7C4D9", width: 1.3 },
    });
  });
  slide.addShape(deck.ShapeType.ellipse, {
    x: centerX, y: centerY, w: 2.7, h: 2.15,
    line: { color: C.red, width: 2 },
    fill: { color: C.red },
  });
  slide.addText(data.keyword || data.takeaway || "核心概念", {
    x: centerX + 0.22, y: centerY + 0.55, w: 2.26, h: 0.72,
    fontSize: 25, bold: true, color: C.white,
    align: "center", valign: "mid", margin: 0, fit: "shrink",
  });
  bullets.forEach((text, itemIndex) => {
    const position = positions[itemIndex];
    slide.addText(text, {
      ...position,
      fontSize: 18, bold: true, color: C.ink,
      align: position.x < centerX ? "right" : "left",
      valign: "mid", margin: 0.08, fit: "shrink",
    });
  });
  slide.addText(data.takeaway || "", {
    x: 3.35, y: 5.58, w: 6.65, h: 0.62,
    fontSize: 20, bold: true, color: C.blue,
    align: "center", margin: 0, fit: "shrink",
  });
  addNotes(slide, data);
}

function addProcessSlide(data, index) {
  const slide = deck.addSlide();
  addHeading(slide, data, index, "理论逻辑");
  const steps = (Array.isArray(data.steps) ? data.steps : []).slice(0, 5);
  const count = Math.max(steps.length, 1);
  const startX = 0.82;
  const totalW = 11.6;
  const stepW = Math.min(2.35, (totalW - (count - 1) * 0.38) / count);
  const gap = count > 1 ? (totalW - count * stepW) / (count - 1) : 0;
  if (count > 1) {
    slide.addShape(deck.ShapeType.chevron, {
      x: startX + stepW * 0.55, y: 3.14,
      w: totalW - stepW * 1.1, h: 0.44,
      line: { color: "C9D4E5", transparency: 100 },
      fill: { color: "DCE5F2" },
    });
  }
  steps.forEach((item, itemIndex) => {
    const x = startX + itemIndex * (stepW + gap);
    slide.addShape(deck.ShapeType.ellipse, {
      x: x + stepW / 2 - 0.42, y: 2.82, w: 0.84, h: 0.84,
      line: { color: itemIndex % 2 ? C.blue : C.red, width: 1.5 },
      fill: { color: itemIndex % 2 ? C.blue : C.red },
    });
    slide.addText(String(itemIndex + 1), {
      x: x + stepW / 2 - 0.24, y: 3.03, w: 0.48, h: 0.28,
      fontFace: "Aptos", fontSize: 16, bold: true,
      color: C.white, align: "center", margin: 0,
    });
    slide.addText(item.title || `步骤${itemIndex + 1}`, {
      x, y: 3.92, w: stepW, h: 0.55,
      fontSize: 21, bold: true, color: C.ink,
      align: "center", margin: 0, fit: "shrink",
    });
    slide.addText(item.description || "", {
      x: x + 0.08, y: 4.65, w: stepW - 0.16, h: 1.0,
      fontSize: 16, color: C.body,
      align: "center", valign: "top", margin: 0, fit: "shrink",
    });
  });
  slide.addText(data.takeaway || "", {
    x: 0.82, y: 1.82, w: 11.5, h: 0.52,
    fontSize: 22, bold: true, color: C.red, margin: 0,
  });
  addNotes(slide, data);
}

function addComparisonSlide(data, index) {
  const slide = deck.addSlide();
  addLightBase(slide, index);
  slide.addText(data.title || "重点辨析", {
    x: 0.72, y: 0.58, w: 11.85, h: 0.64,
    fontSize: 35, bold: true, color: C.ink, margin: 0, fit: "shrink",
  });
  slide.addShape(deck.ShapeType.rect, {
    x: 0.72, y: 1.62, w: 5.76, h: 4.52,
    line: { color: C.redSoft, transparency: 100 },
    fill: { color: C.redSoft },
  });
  slide.addShape(deck.ShapeType.rect, {
    x: 6.48, y: 1.62, w: 5.76, h: 4.52,
    line: { color: C.blueSoft, transparency: 100 },
    fill: { color: C.blueSoft },
  });
  const left = data.left || {};
  const right = data.right || {};
  slide.addText(left.title || "概念一", {
    x: 1.0, y: 1.98, w: 4.95, h: 0.58,
    fontSize: 28, bold: true, color: C.red, margin: 0,
  });
  slide.addText(right.title || "概念二", {
    x: 6.88, y: 1.98, w: 4.95, h: 0.58,
    fontSize: 28, bold: true, color: C.blue, margin: 0,
  });
  addBulletList(slide, left.points?.length ? left.points : data.bullets, {
    x: 1.03, y: 2.88, w: 4.75, h: 2.55,
  }, { fontSize: 18, maximum: 4 });
  addBulletList(slide, right.points?.length ? right.points : data.bullets, {
    x: 6.92, y: 2.88, w: 4.75, h: 2.55,
  }, { fontSize: 18, maximum: 4 });
  slide.addText(data.takeaway || "", {
    x: 2.05, y: 5.7, w: 8.78, h: 0.52,
    fontSize: 20, bold: true, color: C.ink,
    align: "center", margin: 0, fit: "shrink",
  });
  addNotes(slide, data);
}

function addTimelineSlide(data, index) {
  const slide = deck.addSlide();
  addHeading(slide, data, index, "发展脉络");
  const timeline = (Array.isArray(data.timeline) ? data.timeline : []).slice(0, 5);
  const count = Math.max(timeline.length, 1);
  const startX = 1.42;
  const totalW = 10.5;
  const interval = count > 1 ? totalW / (count - 1) : 0;
  slide.addShape(deck.ShapeType.line, {
    x: startX, y: 3.7, w: totalW, h: 0,
    line: { color: C.blue, width: 2.2 },
  });
  timeline.forEach((item, itemIndex) => {
    const x = startX + itemIndex * interval;
    const above = itemIndex % 2 === 0;
    slide.addShape(deck.ShapeType.ellipse, {
      x: x - 0.16, y: 3.54, w: 0.32, h: 0.32,
      line: { color: C.red, width: 1.2 },
      fill: { color: C.red },
    });
    slide.addText(item.label || `阶段${itemIndex + 1}`, {
      x: x - 0.8, y: above ? 2.28 : 4.08, w: 1.6, h: 0.36,
      fontSize: 14, bold: true, color: C.red,
      align: "center", margin: 0, fit: "shrink",
    });
    slide.addText(item.title || "", {
      x: x - 1.08, y: above ? 2.68 : 4.48, w: 2.16, h: 0.72,
      fontSize: 16, bold: true, color: C.ink,
      align: "center", valign: above ? "bottom" : "top",
      margin: 0.02, fit: "shrink",
    });
  });
  slide.addText(data.takeaway || "", {
    x: 0.78, y: 1.77, w: 11.5, h: 0.5,
    fontSize: 22, bold: true, color: C.red, margin: 0,
  });
  addNotes(slide, data);
}

function addDiscussionSlide(data, index) {
  const slide = deck.addSlide();
  slide.background = { color: C.redDark };
  slide.addText("课堂讨论", {
    x: 0.8, y: 0.58, w: 2.5, h: 0.3,
    fontSize: 12, bold: true, color: "E6C67E",
    charSpacing: 2, margin: 0,
  });
  slide.addText(data.title || "请形成你的判断", {
    x: 0.8, y: 1.16, w: 11.5, h: 1.15,
    fontSize: 38, bold: true, color: C.white,
    margin: 0, fit: "shrink",
  });
  slide.addText(data.takeaway || "", {
    x: 0.82, y: 2.62, w: 10.8, h: 0.62,
    fontSize: 21, color: "F2E8EA", margin: 0, fit: "shrink",
  });
  const steps = (Array.isArray(data.steps) && data.steps.length
    ? data.steps
    : cleanArray(data.bullets, 3).map((text, itemIndex) => ({
        title: `步骤${itemIndex + 1}`,
        description: text,
      }))
  ).slice(0, 4);
  const width = 11.15 / Math.max(steps.length, 1);
  steps.forEach((item, itemIndex) => {
    const x = 0.82 + itemIndex * width;
    slide.addText(String(itemIndex + 1).padStart(2, "0"), {
      x, y: 3.82, w: 0.72, h: 0.48,
      fontFace: "Aptos", fontSize: 22, bold: true, color: C.gold, margin: 0,
    });
    slide.addText(item.title || "", {
      x, y: 4.5, w: width - 0.4, h: 0.42,
      fontSize: 20, bold: true, color: C.white, margin: 0, fit: "shrink",
    });
    slide.addText(item.description || "", {
      x, y: 5.08, w: width - 0.4, h: 0.88,
      fontSize: 15, color: "E6DADD", margin: 0, fit: "shrink",
    });
  });
  addFooter(slide, index, true);
  addNotes(slide, data);
}

function addSummarySlide(data, index) {
  const slide = deck.addSlide();
  slide.background = { color: C.paper };
  slide.addShape(deck.ShapeType.rect, {
    x: 0, y: 0, w: 4.6, h: 7.5,
    line: { color: C.blueDark, transparency: 100 },
    fill: { color: C.blueDark },
  });
  slide.addText("总结与应用", {
    x: 0.72, y: 0.72, w: 2.6, h: 0.3,
    fontSize: 12, bold: true, color: "B9CAE5",
    charSpacing: 2, margin: 0,
  });
  slide.addText(data.title || "形成结构化理解", {
    x: 0.72, y: 1.38, w: 3.25, h: 1.65,
    fontSize: 35, bold: true, color: C.white,
    margin: 0, fit: "shrink",
  });
  slide.addText(data.takeaway || "", {
    x: 0.74, y: 3.42, w: 3.15, h: 1.18,
    fontSize: 20, color: "DFE7F3", margin: 0, fit: "shrink",
  });
  const bullets = cleanArray(data.bullets, 5);
  bullets.forEach((text, itemIndex) => {
    const y = 1.05 + itemIndex * 1.06;
    slide.addText(String(itemIndex + 1).padStart(2, "0"), {
      x: 5.2, y, w: 0.7, h: 0.4,
      fontFace: "Aptos", fontSize: 19, bold: true, color: C.red, margin: 0,
    });
    slide.addText(text, {
      x: 6.05, y: y - 0.02, w: 5.82, h: 0.7,
      fontSize: 18, bold: true, color: C.ink,
      margin: 0, fit: "shrink", valign: "mid",
    });
    if (itemIndex < bullets.length - 1) {
      slide.addShape(deck.ShapeType.line, {
        x: 5.2, y: y + 0.82, w: 6.72, h: 0,
        line: { color: C.line, width: 1 },
      });
    }
  });
  addFooter(slide, index);
  addNotes(slide, data);
}

const renderers = {
  title: addTitleSlide,
  agenda: addAgendaSlide,
  question: addQuestionSlide,
  content: addContentSlide,
  concept: addConceptSlide,
  process: addProcessSlide,
  comparison: addComparisonSlide,
  timeline: addTimelineSlide,
  discussion: addDiscussionSlide,
  summary: addSummarySlide,
};

const slides = payload.ppt?.slides || [];
if (!slides.length) throw new Error("PPT 内容为空");
slides.forEach((slideData, index) => {
  if (Array.isArray(slideData.canvas) && slideData.canvas.length >= 3) {
    addCanvasSlide(slideData, index + 1);
    return;
  }
  const layout = index === 0 ? "title" : String(slideData.layout || "content").toLowerCase();
  (renderers[layout] || addContentSlide)(slideData, index + 1);
});

await deck.writeFile({ fileName: outputPath });
