"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Execute the browser's pure time helpers without booting the UI or a server.
const source = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
const start = source.indexOf("function formatProgressTime(");
const end = source.indexOf("function updateRenderProgress(", start);
assert.ok(start >= 0 && end > start, "progress time helpers must remain testable");
const now = 100_000;
const classes = new Set();
const box = { hidden: true, classList: { add: name => classes.add(name), remove: name => classes.delete(name) } };
let timerCallback = null;
const helpers = vm.runInNewContext(
  `${source.slice(start, end)}; ({ formatProgressTime, progressClock, showProgressBox, settleProgressBox })`,
  { Date: { now: () => now }, $: () => box, setTimeout: callback => { timerCallback = callback; return 1; }, clearTimeout: () => {} }
);

assert.equal(helpers.formatProgressTime(0), "0 分 00 秒");
assert.equal(helpers.formatProgressTime(125), "2 分 05 秒");
assert.equal(helpers.formatProgressTime(3661), "1 小时 01 分");
assert.match(helpers.progressClock(40_000, 0, 8), /剩余时间估算中/);
assert.match(helpers.progressClock(40_000, 4, 8, 4), /剩余时间估算中/);
assert.match(helpers.progressClock(40_000, 2, 8), /本阶段约剩 3 分 00 秒/);
assert.match(helpers.progressClock(40_000, 8, 8), /正在核验/);
helpers.showProgressBox();
assert.equal(box.hidden, false);
assert.equal(classes.has("is-active"), true);
helpers.settleProgressBox();
assert.equal(classes.has("is-active"), true, "finished progress remains visible briefly");
timerCallback();
assert.equal(classes.has("is-active"), false);
console.log("进度时间与可见性：11/11 通过");
