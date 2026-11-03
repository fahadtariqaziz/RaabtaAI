import { build } from "esbuild";

await build({
  entryPoints: ["src/index.ts"],
  bundle: true,
  minify: true,
  format: "iife",
  target: ["es2020"],
  outfile: "dist/v1/widget.js",
  legalComments: "none",
});
console.log("built dist/v1/widget.js");
