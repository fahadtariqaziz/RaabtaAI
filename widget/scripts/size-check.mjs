import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";

const LIMIT = 30 * 1024; // PLAN §15.1: <= 30KB gzipped
const gz = gzipSync(readFileSync("dist/v1/widget.js")).length;
console.log(`widget.js gzipped: ${gz} bytes (limit ${LIMIT})`);
if (gz > LIMIT) {
  console.error("FAIL: widget bundle exceeds size budget");
  process.exit(1);
}
