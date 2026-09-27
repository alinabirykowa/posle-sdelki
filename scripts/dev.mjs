import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = process.platform === 'win32' ? path.join(root, '.venv/Scripts/python.exe') : path.join(root, '.venv/bin/python');
if (!existsSync(python)) {
  console.error('Сначала создайте .venv и установите backend/requirements.txt — см. README.md.');
  process.exit(1);
}
const children = [
  spawn(python, ['-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', '8011', '--reload', '--reload-dir', 'backend', ...(existsSync(path.join(root, 'backend/.env')) ? ['--env-file', 'backend/.env'] : [])], {cwd: root, stdio: 'inherit'}),
  spawn(process.platform === 'win32' ? 'npm.cmd' : 'npm', ['--prefix', 'frontend', 'run', 'dev'], {cwd: root, stdio: 'inherit'}),
];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) child.kill('SIGTERM');
  process.exitCode = code;
}
children.forEach(child => {
  child.on('error', error => {console.error(error.message); stop(1);});
  child.on('exit', code => {if (!stopping) stop(code ?? 1);});
});
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
