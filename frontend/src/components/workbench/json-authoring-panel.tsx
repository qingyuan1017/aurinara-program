import * as React from 'react'
import type { AxiosError } from 'axios'
import { Loader2, RotateCcw, Save } from 'lucide-react'
import { DetailHeader } from '@/components/data/detail-header'
import { ErrorState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/sonner'
import { parseProblem, stalenessAlert } from '@/lib/problems'

export interface VersionedPayloadResponse {
  revision: number
  payload: Record<string, unknown>
  fingerprint: string
  state?: string
}

export interface JsonAuthoringPanelProps<T extends object> {
  title: string
  description: React.ReactNode
  value: VersionedPayloadResponse | undefined
  isLoading: boolean
  error: AxiosError | null
  emptyValue: T
  onSave: (value: T) => Promise<VersionedPayloadResponse>
  onReload: () => Promise<unknown> | void
  isSaving: boolean
}

/**
 * Typed JSON authoring surface for versioned clinical contracts that do not yet
 * have a dedicated form designer. It never infers content: the initial value is
 * a blank structural scaffold and every persisted value is authored by a user.
 */
export function JsonAuthoringPanel<T extends object>({
  title,
  description,
  value,
  isLoading,
  error,
  emptyValue,
  onSave,
  onReload,
  isSaving,
}: JsonAuthoringPanelProps<T>) {
  const notFound = error?.response?.status === 404
  const seed = React.useMemo(
    () => JSON.stringify((value?.payload ?? emptyValue) as T, null, 2),
    [emptyValue, value],
  )
  const [draft, setDraft] = React.useState(seed)
  const [parseError, setParseError] = React.useState<string | null>(null)
  const [saveError, setSaveError] = React.useState<string | null>(null)
  const seededRevision = React.useRef<number | null>(null)

  React.useEffect(() => {
    const revision = value?.revision ?? 0
    if (seededRevision.current === revision) return
    seededRevision.current = revision
    setDraft(seed)
    setParseError(null)
    setSaveError(null)
  }, [seed, value?.revision])

  async function handleSave() {
    setParseError(null)
    setSaveError(null)
    let parsed: T
    try {
      const candidate: unknown = JSON.parse(draft)
      if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
        throw new Error('The authored value must be a JSON object.')
      }
      parsed = candidate as T
    } catch (caught) {
      setParseError(caught instanceof Error ? caught.message : 'Invalid JSON.')
      return
    }

    try {
      const saved = await onSave(parsed)
      seededRevision.current = saved.revision
      setDraft(JSON.stringify(saved.payload, null, 2))
      toast.success(`${title} saved.`)
    } catch (caught) {
      const axiosError = caught as AxiosError
      const problem = parseProblem(axiosError)
      setSaveError(
        stalenessAlert(axiosError) ??
          problem.detail ??
          axiosError.message ??
          `Could not save ${title.toLowerCase()}.`,
      )
    }
  }

  if (error && !notFound) {
    return <ErrorState error={error} resourceLabel={title.toLowerCase()} />
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {value ? (
            <DetailHeader
              fields={[
                { label: 'Revision', value: value.revision },
                { label: 'State', value: <StatusBadge status={value.state ?? 'current'} /> },
                {
                  label: 'Fingerprint',
                  value: <code className="break-all text-xs">{value.fingerprint}</code>,
                },
              ]}
            />
          ) : notFound ? (
            <p className="text-muted-foreground text-sm">
              This resource has not been authored. The editor contains a blank
              structural scaffold; complete it before saving.
            </p>
          ) : null}

          <div className="flex flex-col gap-2">
            <Label htmlFor={`json-${title.toLowerCase().replaceAll(' ', '-')}`}>
              Versioned content
            </Label>
            <Textarea
              id={`json-${title.toLowerCase().replaceAll(' ', '-')}`}
              rows={22}
              value={draft}
              disabled={isLoading || isSaving}
              spellCheck={false}
              className="font-mono text-xs"
              aria-invalid={parseError ? true : undefined}
              onChange={(event) => setDraft(event.target.value)}
            />
            <p className="text-muted-foreground text-xs">
              Content is validated by the owning backend module. No mappings,
              assumptions, analyses, or narrative are generated automatically.
            </p>
          </div>

          {(parseError || saveError) && (
            <p role="alert" className="text-destructive text-sm">
              {parseError ?? saveError}
            </p>
          )}

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={isLoading || isSaving}
              onClick={() => {
                seededRevision.current = null
                void onReload()
              }}
            >
              <RotateCcw /> Reload
            </Button>
            <Button type="button" disabled={isLoading || isSaving} onClick={handleSave}>
              {isSaving ? <Loader2 className="animate-spin" /> : <Save />}
              Save
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
