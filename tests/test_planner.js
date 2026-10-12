// Parity check: the browser planner must match the Python reference on the shared vectors.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const P = require("../docs/planner.js");

const vectors = JSON.parse(fs.readFileSync(path.join(__dirname, "vectors.json"), "utf8"));
let n = 0;
for (const { input: c, expected } of vectors) {
  const got = P.plan(c.groups, c.days, c.disk_tb, c.raid, c.reserve, c.disks);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(got)), expected, c.name);
  n++;
}
assert.throws(() => P.plan([], 30, 8), /camera group/);
assert.throws(() => P.plan([{ count: 1, resolution: "9mp" }], 30, 8), /unknown resolution/);
assert.throws(() => P.usableFraction("raid10", 5), /even/);
console.log(`ok - ${n} shared vectors + error cases`);
