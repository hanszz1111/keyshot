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
const helpers = vm.runInNewContext(
  `${source.slice(start, end)}; ({ formatProgressTime, progressClock })`,
  { Date: { now: () => now } }
);

assert.equal(helpers.formatProgressTime(0), "0 分 00 秒");
assert.equal(helpers.formatProgressTime(125), "2 分 05 秒");
assert.equal(helpers.formatProgressTime(3661), "1 小时 01 分");
assert.match(helpers.progressClock(40_000, 0, 8), /剩余时间估算中/);
assert.match(helpers.progressClock(40_000, 4, 8, 4), /剩余时间估算中/);
assert.match(helpers.progressClock(40_000, 2, 8), /本阶段约剩 3 分 00 秒/);
assert.match(helpers.progressClock(40_000, 8, 8), /正在核验/);
console.log("进度时间估算：7/7 通过");
