import { useState } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/page-header'
import { DetailHeader } from '@/components/data/detail-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { ErrorState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatDate } from '@/lib/utils'
import {
  useGetRelease,
  useGetTerminologyAssetContent,
  useListCodelists,
  useListTerminologyAssets,
  useListTerminologyCompatibilities,
} from '@/api/generated/provider-catalogs/provider-catalogs'
import type {
  CodelistResponse,
  TerminologyAssetResponse,
  TerminologyCompatibilityResponse,
} from '@/api/generated/model'

export const Route = createFileRoute('/_app/standards/releases/$releaseId')({
  component: TerminologyReleasePage,
})

function AssetContentDialog({
  asset,
  onClose,
}: {
  asset: TerminologyAssetResponse | null
  onClose: () => void
}) {
  const { data, isLoading, isError, error } = useGetTerminologyAssetContent(
    asset?.id ?? '',
    { query: { enabled: asset !== null } },
  )

  return (
    <Dialog open={asset !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[80vh] max-w-3xl overflow-hidden">
        <DialogHeader>
          <DialogTitle>{asset?.title ?? asset?.role ?? 'Asset content'}</DialogTitle>
          <DialogDescription>
            {asset?.canonical_href ?? asset?.media_type ?? 'Terminology asset'}
          </DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : isError ? (
          <ErrorState error={error} resourceLabel="asset content" />
        ) : (
          <pre className="bg-muted max-h-[60vh] overflow-auto rounded-md p-4 text-xs">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}
      </DialogContent>
    </Dialog>
  )
}

const codelistColumns: ResourceColumn<CodelistResponse>[] = [
  { key: 'code', header: 'Code' },
  { key: 'name', header: 'Name' },
  {
    key: 'submission_value',
    header: 'Submission value',
    cell: (row) => row.submission_value ?? '—',
  },
  {
    key: 'concept_id',
    header: 'Concept id',
    cell: (row) => row.concept_id ?? '—',
  },
  {
    key: 'extensible',
    header: 'Extensible',
    cell: (row) => (row.extensible ? 'Yes' : 'No'),
  },
]

const compatibilityColumns: ResourceColumn<TerminologyCompatibilityResponse>[] =
  [
    { key: 'relationship', header: 'Relationship' },
    { key: 'standard_version_id', header: 'Standard version id' },
    { key: 'terminology_scope', header: 'Terminology scope' },
    { key: 'standard_purpose', header: 'Standard purpose' },
  ]

function buildAssetColumns(
  onView: (asset: TerminologyAssetResponse) => void,
): ResourceColumn<TerminologyAssetResponse>[] {
  return [
    { key: 'role', header: 'Role' },
    { key: 'media_type', header: 'Media type' },
    { key: 'title', header: 'Title', cell: (row) => row.title ?? '—' },
    {
      key: 'resource_type',
      header: 'Resource type',
      cell: (row) => row.resource_type ?? '—',
    },
    {
      key: 'canonical_href',
      header: 'Canonical href',
      cell: (row) =>
        row.canonical_href ? (
          <a
            href={row.canonical_href}
            target="_blank"
            rel="noreferrer"
            className="underline"
            onClick={(event) => event.stopPropagation()}
          >
            link
          </a>
        ) : (
          '—'
        ),
    },
    {
      key: 'content',
      header: 'Content',
      cell: (row) => (
        <Button
          variant="outline"
          size="sm"
          onClick={(event) => {
            event.stopPropagation()
            onView(row)
          }}
        >
          View
        </Button>
      ),
    },
  ]
}

function TerminologyReleasePage() {
  const { releaseId } = Route.useParams()
  const navigate = useNavigate()
  const [selectedAsset, setSelectedAsset] =
    useState<TerminologyAssetResponse | null>(null)
  const assetColumns = buildAssetColumns(setSelectedAsset)

  const { data: release, isLoading, isError, error } = useGetRelease(releaseId)

  const codelists = useListCodelists(releaseId)
  const compatibilities = useListTerminologyCompatibilities(releaseId)
  const assets = useListTerminologyAssets(releaseId)

  return (
    <div className="flex flex-col gap-6">
      <Button asChild variant="ghost" className="w-fit">
        <Link to="/standards">Back to standards</Link>
      </Button>

      <PageHeader
        title={
          release ? `${release.code} ${release.version}` : 'Terminology release'
        }
      />

      {isError ? (
        <ErrorState error={error} resourceLabel="terminology release" />
      ) : isLoading ? (
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-3">
          {Array.from({ length: 9 }).map((_, index) => (
            <Skeleton key={index} className="h-10 w-full" />
          ))}
        </div>
      ) : release ? (
        <DetailHeader
          fields={[
            { label: 'Code', value: release.code },
            { label: 'Version', value: release.version },
            { label: 'Provider', value: release.provider },
            { label: 'Product', value: release.product },
            {
              label: 'Lifecycle',
              value: <StatusBadge status={release.lifecycle} />,
            },
            { label: 'Content schema', value: release.content_schema_version },
            {
              label: 'Publication date',
              value: formatDate(release.publication_date),
            },
            { label: 'Created', value: formatDate(release.created_at) },
            {
              label: 'Applicable modules',
              value: release.applicable_modules.join(', ') || '—',
            },
          ]}
        />
      ) : null}

      <Tabs defaultValue="codelists">
        <TabsList>
          <TabsTrigger value="codelists">Codelists</TabsTrigger>
          <TabsTrigger value="compatibilities">Compatibilities</TabsTrigger>
          <TabsTrigger value="assets">Assets</TabsTrigger>
        </TabsList>
        <TabsContent value="codelists">
          <ResourceTable
            columns={codelistColumns}
            rows={codelists.data ?? []}
            getRowId={(row) => row.id}
            isLoading={codelists.isLoading}
            isError={codelists.isError}
            error={codelists.error}
            resourceLabel="codelists"
            onRowClick={(row) =>
              navigate({
                to: '/standards/codelists/$codelistId',
                params: { codelistId: row.id },
              })
            }
          />
        </TabsContent>
        <TabsContent value="compatibilities">
          <ResourceTable
            columns={compatibilityColumns}
            rows={compatibilities.data ?? []}
            getRowId={(row) => row.id}
            isLoading={compatibilities.isLoading}
            isError={compatibilities.isError}
            error={compatibilities.error}
            resourceLabel="compatibilities"
          />
        </TabsContent>
        <TabsContent value="assets">
          <ResourceTable
            columns={assetColumns}
            rows={assets.data ?? []}
            getRowId={(row) => row.id}
            isLoading={assets.isLoading}
            isError={assets.isError}
            error={assets.error}
            resourceLabel="assets"
          />
        </TabsContent>
      </Tabs>

      <AssetContentDialog
        asset={selectedAsset}
        onClose={() => setSelectedAsset(null)}
      />
    </div>
  )
}
