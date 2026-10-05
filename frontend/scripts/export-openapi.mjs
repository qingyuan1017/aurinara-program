// Exports the backend OpenAPI document to frontend/openapi.json without needing
// a running server. Runs the FastAPI app factory through `uv` and dumps the
// schema. Orval then reads the file to generate the typed client + hooks.
//
// Usage: node scripts/export-openapi.mjs
import { spawnSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(dirname, '..', '..')
const outFile = path.resolve(dirname, '..', 'openapi.json')

const pyCode = [
  'import json, os',
  "os.environ.setdefault('APP_ENV', 'test')",
  'from app.main import create_app',
  'app = create_app()',
  'print(json.dumps(app.openapi()))',
].join('; ')

const result = spawnSync('uv', ['run', 'python', '-c', pyCode], {
  cwd: repoRoot,
  encoding: 'utf-8',
  maxBuffer: 64 * 1024 * 1024,
  shell: process.platform === 'win32',
})

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
