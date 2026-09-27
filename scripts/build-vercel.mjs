/** Build frontend assets for the FastAPI preset's documented public/ CDN. */
import { spawnSync } from "node:child_process";
import { cp, mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const root = fileURLToPath(new URL("../", import.meta.url));
const frontend = join(root, "frontend");
const args = process.argv.slice(2);
if (args.some((arg) => arg !== "--skip-install")) {
  throw new Error("Usage: node scripts/build-vercel.mjs [--skip-install]");
}

function npm(command) {
  const result = spawnSync("npm", command, {
    cwd: frontend,
    stdio: "inherit",
    shell: false,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

// Vercel installs Python packages automatically. Install the separate locked
// frontend dependencies here; --skip-install is only for local build checks.
if (!args.includes("--skip-install")) npm(["ci", "--include=dev"]);
npm(["run", "build"]);

const dist = join(frontend, "dist");
await readFile(join(dist, "index.html"), "utf8");
await mkdir(join(root, "public"), { recursive: true });
await cp(dist, join(root, "public"), { recursive: true });
console.log("Vercel frontend ready: public/index.html and public/assets/");
