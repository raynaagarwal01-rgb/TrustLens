// Builds the interface into web/dist, which server.py serves.
//   npm run build        one-off production build
//   npm run watch        rebuild on change (run `python server.py` alongside)
import * as esbuild from "esbuild";
import { cpSync, mkdirSync, rmSync } from "node:fs";

const watch = process.argv.includes("--watch");
rmSync("dist", { recursive: true, force: true });
mkdirSync("dist/assets", { recursive: true });
cpSync("public", "dist", { recursive: true });

const options = {
  entryPoints: { app: "src/main.tsx" },
  bundle: true,
  outdir: "dist/assets",
  format: "esm",
  jsx: "automatic",
  minify: !watch,
  sourcemap: watch,
  target: ["es2022", "chrome110", "firefox110", "safari16"],
  loader: { ".woff": "file" },
  external: ["/fonts/*"],
  define: { "process.env.NODE_ENV": watch ? '"development"' : '"production"' },
  logLevel: "info",
};

if (watch) {
  const ctx = await esbuild.context(options);
  await ctx.watch();
} else {
  await esbuild.build(options);
}
