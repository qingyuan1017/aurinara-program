import { createFileRoute, Link } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/page-header'
import { DetailHeader } from '@/components/data/detail-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { ErrorState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/utils'
import {
  useGetTemplate,
  useListTemplateVersions,
} from '@/api/generated/provider-catalogs/provider-catalogs'
import type { TemplateVersionResponse } from '@/api/generated/model'

export const Route = createFileRoute('/_app/standards/templates/$templateId')({
  component: TemplatePage,
})

const versionColumns: ResourceColumn<TemplateVersionResponse>[] = [
  { key: 'version', header: 'Version' },
  {
    key: 'lifecycle',
    header: 'Lifecycle',
    cell: (row) => <StatusBadge status={row.lifecycle} />,
  },
  { key: 'checksum', header: 'Checksum' },
  {
    key: 'artifact_types',
    header: 'Artifact types',
    cell: (row) => row.artifact_types.join(', ') || '—',
  },
  {
    key: 'content_schema_versions',
    header: 'Content schema versions',
    cell: (row) => row.content_schema_versions.join(', ') || '—',
  },
  {
    key: 'created_at',
    header: 'Created',
    cell: (row) => formatDate(row.created_at),
  },
]

function TemplatePage() {
  const { templateId } = Route.useParams()

  const {
    data: template,
    isLoading,
    isError,
    error,
  } = useGetTemplate(templateId)

  const versions = useListTemplateVersions(templateId)

  return (
    <div className="flex flex-col gap-6">
      <Button asChild variant="ghost" className="w-fit">
        <Link to="/standards">Back to standards</Link>
      </Button>

      <PageHeader
        title={template ? `${template.code} — ${template.name}` : 'Template'}
      />

      {isError ? (
        <ErrorState error={error} resourceLabel="template" />
      ) : isLoading ? (
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-3">
          {Array.from({ length: 2 }).map((_, index) => (
            <Skeleton key={index} className="h-10 w-full" />
          ))}
        </div>
      ) : template ? (
        <DetailHeader
          fields={[
            { label: 'Code', value: template.code },
            { label: 'Name', value: template.name },
          ]}
        />
      ) : null}

      <ResourceTable
        columns={versionColumns}
        rows={versions.data ?? []}
        getRowId={(row) => row.id}
        isLoading={versions.isLoading}
        isError={versions.isError}
        error={versions.error}
        resourceLabel="template versions"
      />
    </div>
  )
}
