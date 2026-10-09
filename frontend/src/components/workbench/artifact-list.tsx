import * as React from 'react'
import type { ArtifactResponse } from '@/api/generated/model'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { EmptyState } from '@/components/data/states'
import { formatBytes } from '@/lib/utils'
import { DownloadButton } from './download-button'

/**
 * The subset of {@link ArtifactResponse} needed to render a produced artifact
 * row. Operation resources carry only `result_artifact_ids: string[]`, so a
 * caller resolves those ids to artifact metadata and passes them here; when
 * only ids are known a bare `{ id }` is enough to render a download action.
 */
export type ArtifactListItem =
  | ArtifactResponse
  | (Pick<ArtifactResponse, 'id'> & Partial<ArtifactResponse>)

interface ArtifactRowProps {
  artifact: ArtifactListItem
}

function ArtifactRow({ artifact }: ArtifactRowProps) {
  const bytes = typeof artifact.size === 'number' ? formatBytes(artifact.size) : null
  return (
    <li className="border-border flex items-center justify-between gap-3 border-b py-3 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="truncate text-sm font-medium">
            {artifact.filename ?? artifact.id}
          </span>
          {artifact.artifact_type && (
            <code className="text-muted-foreground text-xs">
              {artifact.artifact_type}
            </code>
          )}
        </div>
        <dl className="text-muted-foreground mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs">
          {artifact.media_type && (
            <div>
              <dt className="inline font-medium">Type: </dt>
              <dd className="inline">{artifact.media_type}</dd>
            </div>
          )}
          {bytes && (
            <div>
              <dt className="inline font-medium">Size: </dt>
              <dd className="inline">{bytes}</dd>
            </div>
          )}
          {artifact.sha256 && (
            <div>
              <dt className="inline font-medium">SHA-256: </dt>
              <dd className="inline break-all" title={artifact.sha256}>
                {artifact.sha256.slice(0, 12)}…
              </dd>
            </div>
          )}
        </dl>
      </div>
      <DownloadButton
        artifactId={artifact.id}
        filename={artifact.filename}
      />
    </li>
  )
}

export interface ArtifactListProps {
  /**
   * The produced artifacts to list. Each exposes a download action retrieving
   * it through `GET /api/v1/artifacts/{artifact_id}/download` (Requirement 8.4).
   */
  artifacts: ReadonlyArray<ArtifactListItem>
  /** Card title. Defaults to "Artifacts". */
  title?: string
  /** Empty-state title shown when `artifacts` is empty. */
  emptyTitle?: string
  emptyDescription?: React.ReactNode
}

/**
 * Lists produced artifacts with a per-row {@link DownloadButton}. Rendered by
 * {@link OperationRunner} when a build/run reaches a successful terminal status
 * (Requirement 8.4). It is never rendered for a `failed` terminal — the runner
 * presents the typed failure and no download instead (Requirement 8.5).
 */
export function ArtifactList({
  artifacts,
  title = 'Artifacts',
  emptyTitle = 'No artifacts',
  emptyDescription = 'This operation produced no downloadable artifacts.',
}: ArtifactListProps) {
  if (artifacts.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>
          {artifacts.length} artifact{artifacts.length === 1 ? '' : 's'} produced
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="list-none">
          {artifacts.map((artifact) => (
            <ArtifactRow key={artifact.id} artifact={artifact} />
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

export default ArtifactList
