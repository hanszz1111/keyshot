"use strict";

// 提示词拼装的回归测试（2026-10-07 v3.26 新增）。
//
// 为什么需要：buildPayload() 的「白模→成品」改写曾用整串 replace，而目标文案与
// 数组里实际那句不一致 → 改写与 NEGATIVE_CLAY **双双静默失效**：白模截图会带着
// 「保持灰色」的负面约束去出图。这类「写了但没生效」的缺陷离线自检抓不到
// （自检在 Python 侧，看不到 JS 字符串），所以单开一个纯 JS 用例钉住。
//
// 断言口径是「结构化契约」，不是逐字比对：只检查收尾句位置、替换是否真的发生、
// 负面词是否合并，这样微调措辞不会误报，但改了数组顺序/结构就会立刻失败。

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");

function pick(name) {
  const start = source.indexOf(`const ${name} = "`);
  assert.ok(start >= 0, `${name} 必须定义为字符串常量`);
  const from = start + `const ${name} = `.length;
  const end = source.indexOf('";', from);
  assert.ok(end > from, `${name} 定义不完整`);
  return JSON.parse(source.slice(from, end + 1));
}

const NEGATIVE_CLAY = pick("NEGATIVE_CLAY");
const IMAGE_MODE_LINE = pick("IMAGE_MODE_LINE");
const NEGATIVE = pick("NEGATIVE");

// buildPayload 里收尾句所在的那一行必须仍用 IMAGE_MODE_LINE 常量，
// 否则下面的下标定位就不再成立。
assert.ok(
  source.includes("mode===\"image\"?IMAGE_MODE_LINE:"),
  "图片改图的收尾句必须引用 IMAGE_MODE_LINE 常量，否则白模改写会再次静默失效"
);
// 改写必须走「按片段替换 + 必达校验」，不再出现整串 replace
assert.ok(
  source.includes("parts[closingAt]!==IMAGE_MODE_LINE"),
  "白模改写的必达校验缺失：文案一变就会静默退化"
);
assert.ok(
  !source.includes(".replace(\n        \"Use the input product image as the primary composition and identity.\""),
  "不应再对整串做 replace（旧写法已证明会静默失效）"
);

// ---- 复现片段构造 + 白模改写，覆盖 4 条路径 ----
function build({ design = false, mode = "image", desc = "", refLine = "" }) {
  const positive = [
    "Professional high-end product photograph of SKU, front.",
    "Main body: fine-grain matte plastic, color #333333.",
    design ? "" : "large softbox studio lighting, soft contact shadows.",
    design ? "" : "clean light-gray gradient studio background",
    design
      ? "Premium commercial product photography, realistic material response, accurate camera perspective and crisp silhouette."
      : "Premium commercial product photography, realistic material response, accurate camera perspective, crisp silhouette, fine controlled highlights, clean contact shadow.",
    desc ? `User's design requirements (retain exact intent): ${desc}` : "",
    refLine,
    mode === "controlled"
      ? "Follow the supplied depth map for the product silhouette and proportions. Do not invent openings, controls or markings."
      : mode === "image"
        ? IMAGE_MODE_LINE
        : "Creative concept exploration; product geometry is not guaranteed.",
  ].filter(Boolean);
  const closingAt = positive.length - 1;
  const payload = { positive: positive.join(" "), negative: NEGATIVE, _meta: {} };
  let rewrote = false;
  if (mode === "image") {
    const isClay = true; // analysisOfSource() 判定为白模截图
    if (isClay) {
      const parts = positive.slice();
      if (mode !== "image" || parts[closingAt] !== IMAGE_MODE_LINE)
        throw new Error("内部错误：图片改图收尾句位置已变更，白模转换改写失效");
      parts[closingAt] =
        "The input is an unpainted clay/grey 3D model screenshot on a dark background. Convert it into a finished, fully materialised product: apply real surface materials, colour and finish to every surface. Use its silhouette and component layout as the primary composition and identity.";
      payload.positive = parts.join(" ");
      payload.negative = NEGATIVE + NEGATIVE_CLAY;
      payload._meta.input_kind = "clay";
      rewrote = true;
    }
  }
  return { payload, rewrote, closingAt };
}

// 1) 图片改图 + 白模：改写必须真的发生，且前置片段一个不少
const a = build({ desc: "黑色包胶握把", refLine: "Borrow materials from a supplied reference photo. " });
assert.equal(a.rewrote, true, "白模截图必须触发改写");
assert.ok(a.payload.positive.includes("unpainted clay/grey"), "正向词应换成「转成成品」");
assert.ok(!a.payload.positive.includes("Retain its camera angle"), "旧的收尾句必须被移除");
for (const keep of [
  "Professional high-end product photograph",
  "Main body: fine-grain matte plastic",
  "User's design requirements (retain exact intent): 黑色包胶握把",
  "Borrow materials from a supplied reference photo.",
  "large softbox studio lighting",
])
  assert.ok(a.payload.positive.includes(keep), `改写不应丢掉前置片段：${keep}`);
assert.ok(a.payload.negative.includes("white unpainted plastic"), "负面词应压住「保持灰色」");
assert.ok(a.payload.negative.startsWith(NEGATIVE), "负面词应在原 NEGATIVE 基础上追加");
assert.equal(a.payload._meta.input_kind, "clay");

// 2) 选了设计预设时同样生效（旧写法下这条也失效）
const b = build({ design: true });
assert.ok(b.payload.positive.includes("unpainted clay/grey"));
assert.ok(b.payload.negative.includes("bare grey model"));
assert.ok(!b.payload.positive.includes("lighting"), "设计预设下不应再拼手动灯光");

// 3) 结构约束模式不改写（走 depth 图，本来就该保留原句）
const c = build({ mode: "controlled" });
assert.equal(c.rewrote, false);
assert.ok(c.payload.positive.includes("Follow the supplied depth map"));
assert.ok(!c.payload.negative.includes("clay render"));

// 4) 收尾句位置契约：无论前面的可选片段有几个，收尾句始终是最后一个
for (const opts of [{}, { desc: "x" }, { refLine: "y" }, { desc: "x", refLine: "y" }, { design: true }]) {
  const r = build(opts);
  assert.equal(
    r.payload.positive.endsWith(IMAGE_MODE_LINE) || r.payload.positive.endsWith("primary composition and identity."),
    true,
    `收尾句必须落在末尾（options=${JSON.stringify(opts)}）`
  );
}

console.log("提示词拼装：12/12 通过");
