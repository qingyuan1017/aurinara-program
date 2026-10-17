import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { AxiosError } from 'axios'
import { Database, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { FileDropzone } from '@/components/workbench/file-dropzone'
import { useWorkbench } from '@/components/workbench/workbench-context'
import { useCreateSourceFile } from '@/api/generated/artifacts/artifacts'
import type { SourceFileResponse } from '@/api/generated/model'
import {
  importDomain,
  useGetImportedDomain,
} from '@/api/generated/sdtm/sdtm'
import { invalidateSdtmSubResource } from '@/lib/invalidate'
import { parseProblem } from '@/lib/problems'

interface ImportedVariable {
  name?: string
  data_type?: string
  length?: number | null
}

export function ImportedSdtmDomainPanel({
  sdtmId,
  domainCode,
  specificationRevision,
}: {
  sdtmId: string
  domainCode: string
  specificationRevision: number
}) {
  const qc = useQueryClient()
  const workbench = useWorkbench()
  const imported = useGetImportedDomain(sdtmId, domainCode, {
    query: { retry: false },
  })
  const upload = useCreateSourceFile()
  const [source, setSource] = React.useState<SourceFileResponse | null>(null)
  const [isImporting, setIsImporting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  async function handleFiles(files: File[]) {
    const file = files[0]
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.xpt')) {
      setError('Choose a SAS XPORT v5 file with the .xpt extension.')
      return
    }
    setError(null)
    setSource(null)
    try {
      const uploaded = await upload.mutateAsync({
        studyId: workbench.studyId,
        data: { file: file as unknown as string },
      })
      setSource(uploaded)
    } catch (caught) {
      const problem = parseProblem(caught as AxiosError)
      setError(problem.detail ?? 'The XPT source file could not be uploaded.')
    }
  }

  async function acceptImport() {
    if (!source) return
    setIsImporting(true)
    setError(null)
    try {
      const ifMatch = workbench.ifMatch()
      await importDomain(
        sdtmId,
        domainCode,
        {
          source_file_id: source.id,
          expected_sha256: source.sha256,
          specification_revision: specificationRevision,
        },
        {
          ...ifMatch,
          headers: {
            ...ifMatch.headers,
            'Idempotency-Key': crypto.randomUUID(),
          },
        },
      )
      setSource(null)
      invalidateSdtmSubResource(qc, 'domain-mapping', sdtmId, true, domainCode)
      toast.success(`${domainCode} imported and selected as the domain source.`)
    } catch (caught) {
      const problem = parseProblem(caught as AxiosError)
      setError(problem.detail ?? `Could not import ${domainCode}.`)
    } finally {
      setIsImporting(false)
    }
  }

  const schema = imported.data?.extracted_schema as
    | { row_count?: number; variables?: ImportedVariable[] }
    | undefined
  const notFound = imported.error?.response?.status === 404

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <Database className="size-4" /> {domainCode} domain source
            </CardTitle>
            <CardDescription>
              Upload an existing SDTM XPORT v5 dataset to use it directly in
              downstream <code>sdtm_read</code> nodes. Extracted physical metadata
              is reviewed against the Specification and never overwrites it.
            </CardDescription>
          </div>
          {imported.data && (
            <Badge variant={imported.data.selected_as_source ? 'default' : 'outline'}>
              {imported.data.selected_as_source
                ? `Imported source · r${imported.data.revision}`
                : `Import available · r${imported.data.revision}`}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {imported.data && (
          <div className="text-muted-foreground grid gap-2 rounded-md border p-3 text-sm sm:grid-cols-3">
            <div><span className="font-medium text-foreground">Rows:</span> {schema?.row_count ?? '—'}</div>
            <div><span className="font-medium text-foreground">Variables:</span> {schema?.variables?.length ?? '—'}</div>
            <div><span className="font-medium text-foreground">Artifact:</span> <code>{imported.data.artifact_id.slice(0, 8)}</code></div>
            {schema?.variables && schema.variables.length > 0 && (
              <div className="sm:col-span-3">
                <span className="font-medium text-foreground">Schema:</span>{' '}
                {schema.variables.map((variable) =>
                  `${variable.name ?? '?'} (${variable.data_type ?? '?'}${variable.length ? ` ${variable.length}` : ''})`,
                ).join(', ')}
              </div>
            )}
          </div>
        )}

        <FileDropzone
          accept=".xpt,application/vnd.ms-excel,application/octet-stream"
          onFiles={handleFiles}
          disabled={upload.isPending || isImporting}
          ariaLabel={`Upload existing ${domainCode} XPT`}
          label={upload.isPending ? 'Uploading XPT…' : `Drop ${domainCode}.xpt here, or browse`}
          description="The original upload and accepted SDTM artifact remain immutable."
        />

        {source && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3 text-sm">
            <div>
              <div className="font-medium">{source.filename}</div>
              <div className="text-muted-foreground">
                {source.size.toLocaleString()} bytes · SHA-256 {source.sha256.slice(0, 12)}…
              </div>
            </div>
            <Button onClick={acceptImport} disabled={isImporting}>
              {isImporting && <Loader2 className="animate-spin" />}
              Use as {domainCode} source
            </Button>
          </div>
        )}

        {error && <p className="text-destructive text-sm" role="alert">{error}</p>}
        {imported.isError && !notFound && (
          <p className="text-destructive text-sm" role="alert">
            {parseProblem(imported.error as AxiosError).detail ?? 'Could not load the imported domain.'}
          </p>
        )}
        {imported.data?.issues && imported.data.issues.length > 0 && (
          <div className="rounded-md border p-3 text-sm">
            <div className="mb-2 font-medium">Import review findings</div>
            <ul className="list-disc space-y-1 pl-5">
              {imported.data.issues.map((issue, index) => (
                <li key={String(issue.id ?? issue.code ?? index)}>
                  {String(issue.message ?? issue.code ?? 'Review finding')}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
