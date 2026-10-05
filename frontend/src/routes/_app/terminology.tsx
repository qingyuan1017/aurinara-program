import { createFileRoute } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCurrentStudy } from '@/components/study-provider'
import { useListReleases } from '@/api/generated/provider-catalogs/provider-catalogs'
import { useListExtensions } from '@/api/generated/terminology/terminology'
import type {
  ExtensionResponse,
  TerminologyReleaseResponse,
} from '@/api/generated/model'

export const Route = createFileRoute('/_app/terminology')({
  component: TerminologyPage,
})

const releaseColumns: ResourceColumn<TerminologyReleaseResponse>[] = [
  { key: 'code', header: 'Code' },
  { key: 'version', header: 'Version' },
  { key: 'provider', header: 'Provider' },
  { key: 'product', header: 'Product' },
  {
    key: 'lifecycle',
    header: 'Lifecycle',
    cell: (row) => <StatusBadge status={row.lifecycle} />,
  },
  { key: 'content_schema_version', header: 'Content schema' },
]

const extensionColumns: ResourceColumn<ExtensionResponse>[] = [
  { key: 'code', header: 'Code' },
  { key: 'name', header: 'Name' },
  { key: 'codelist_code', header: 'Codelist' },
  {
    key: 'status',
    header: 'Status',
    cell: (row) => <StatusBadge status={row.status} />,
  },
  { key: 'revision', header: 'Revision' },
]

function ReleasesTab() {
  const { data, isLoading, isError, error } = useListReleases()
  return (
    <ResourceTable
      columns={releaseColumns}
      rows={data ?? []}
      getRowId={(row) => row.id}
      isLoading={isLoading}
      isError={isError}
      error={error}
      resourceLabel="terminology releases"
    />
  )
}

function ExtensionsTab() {
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListExtensions(
    currentStudyId ?? '',
    { query: { enabled: !!currentStudyId } },
  )
  return (
    <ResourceTable
      columns={extensionColumns}
      rows={data ?? []}
      getRowId={(row) => row.id}
      isLoading={isLoading || studiesLoading}
      isError={isError}
      error={error}
      resourceLabel="study extensions"
      emptyState={
        !studiesLoading && !currentStudyId ? (
          <EmptyState
            title="No study selected"
            description="Create a study first to view its terminology extensions."
          />
        ) : undefined
      }
    />
  )
}

function TerminologyPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Terminology"
        description="Terminology releases from the provider catalog and the current study's extensions."
      />
      <Tabs defaultValue="releases">
        <TabsList>
          <TabsTrigger value="releases">Releases</TabsTrigger>
          <TabsTrigger value="extensions">Study extensions</TabsTrigger>
        </TabsList>
        <TabsContent value="releases">
          <ReleasesTab />
        </TabsContent>
        <TabsContent value="extensions">
          <ExtensionsTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
