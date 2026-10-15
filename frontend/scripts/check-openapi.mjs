// Verify that the checked-in frontend contract matches the live FastAPI app
// without rewriting any tracked files. CI should run this before typecheck.
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'
import path from 'node:path'

const dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(dirname, '..')
const repoRoot = path.resolve(frontendRoot, '..')
const snapshotFile = path.join(frontendRoot, 'openapi.json')

const pyCode = [
  'import json, os',
  "os.environ.setdefault('APP_ENV', 'test')",
  'from app.main import create_app',
  'print(json.dumps(create_app().openapi(), sort_keys=True, separators=(\",\", \":\")))',
].join('\n')

const scriptDir = mkdtempSync(path.join(tmpdir(), 'aurinara-openapi-check-'))
const scriptFile = path.join(scriptDir, 'check_openapi.py')
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
  console.error('Failed to read the live FastAPI OpenAPI contract.')
  if (result.stderr) console.error(result.stderr)
  process.exit(result.status ?? 1)
}

const start = result.stdout.indexOf('{')
if (start === -1) {
  console.error('The FastAPI exporter did not emit a JSON object.')
  process.exit(1)
}

const canonical = (value) => JSON.stringify(value)
const normalize = (value) => {
  if (Array.isArray(value)) return value.map(normalize)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, normalize(entry)]),
    )
  }
  return value
}

const live = JSON.parse(result.stdout.slice(start).trim())
const snapshot = JSON.parse(readFileSync(snapshotFile, 'utf-8'))

if (canonical(normalize(live)) !== canonical(normalize(snapshot))) {
  console.error(
    'frontend/openapi.json is out of date. Run `npm run api:sync` and commit the regenerated client.',
  )
  process.exit(1)
}

console.log(
  `OpenAPI snapshot is current (${Object.keys(live.paths ?? {}).length} paths, ` +
    `${Object.keys(live.components?.schemas ?? {}).length} schemas).`,
)
