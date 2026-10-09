// Exports the backend OpenAPI document to frontend/openapi.json without needing
// a running server. Runs the FastAPI app factory through `uv` and dumps the
// schema. Orval then reads the file to generate the typed client + hooks.
//
// Usage: node scripts/export-openapi.mjs
import { spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'
import path from 'node:path'

const dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(dirname, '..', '..')
const outFile = path.resolve(dirname, '..', 'openapi.json')

// The Python snippet is written to a temporary file rather than passed via
// `python -c`. On Windows `spawnSync` needs `shell: true` to resolve the `uv`
// executable, but a shell re-parses the argument list and the `;` statement
// separators in an inline snippet get split into broken shell commands. A
// temp file sidesteps all shell-quoting issues and stays cross-platform.
const pyCode = [
  'import json, os',
  "os.environ.setdefault('APP_ENV', 'test')",
  'from app.main import create_app',
  'app = create_app()',
  'print(json.dumps(app.openapi()))',
].join('\n')

// Write the exporter to a temp .py file instead of passing it via `-c`. On
// Windows, spawning through the shell re-splits an inline `-c` string on its
// spaces/semicolons, so a file argument is the portable way to run it.
const scriptDir = mkdtempSync(path.join(tmpdir(), 'aurinara-openapi-'))
const scriptFile = path.join(scriptDir, 'export_openapi.py')
writeFileSync(scriptFile, pyCode, 'utf-8')

let result
try {
  result = spawnSync('uv', ['run', 'python', scriptFile], {
    cwd: repoRoot,
    encoding: 'utf-8',
    maxBuffer: 64 * 1024 * 1024,
    shell: process.platform === 'win32',
  })
} finally {
  rmSync(scriptDir, { recursive: true, force: true })
}

if (result.status !== 0) {
  console.error('Failed to export OpenAPI schema from the backend.')
  if (result.stderr) console.error(result.stderr)
  process.exit(result.status ?? 1)
}

const start = result.stdout.indexOf('{')
if (start === -1) {
  console.error('No JSON object found in backend output.')
  console.error(result.stdout)
  process.exit(1)
}

const json = result.stdout.slice(start).trim()
// Validate and pretty-print before writing.
const parsed = JSON.parse(json)
writeFileSync(outFile, JSON.stringify(parsed, null, 2) + '\n', 'utf-8')
console.log(
  `Wrote ${outFile} (${Object.keys(parsed.paths ?? {}).length} paths, ` +
    `${Object.keys(parsed.components?.schemas ?? {}).length} schemas).`,
)
