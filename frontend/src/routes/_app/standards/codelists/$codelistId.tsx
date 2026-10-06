import { createFileRoute, Link } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/page-header'
import { DetailHeader } from '@/components/data/detail-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { ErrorState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useGetCodelist,
  useListTerms,
} from '@/api/generated/provider-catalogs/provider-catalogs'
import type { TermResponse } from '@/api/generated/model'

export const Route = createFileRoute('/_app/standards/codelists/$codelistId')({
  component: CodelistPage,
})

const termColumns: ResourceColumn<TermResponse>[] = [
  { key: 'code', header: 'Code' },
  { key: 'submission_value', header: 'Submission value' },
  { key: 'decode', header: 'Decode', className: 'max-w-sm truncate' },
  {
    key: 'concept_id',
    header: 'Concept id',
    cell: (row) => row.concept_id ?? '—',
  },
  {
    key: 'preferred_term',
    header: 'Preferred term',
    cell: (row) => row.preferred_term ?? '—',
  },
  {
    key: 'status',
    header: 'Status',
    cell: (row) => <StatusBadge status={row.status} />,
  },
]

function CodelistPage() {
  const { codelistId } = Route.useParams()

  const {
    data: codelist,
    isLoading,
    isError,
    error,
  } = useGetCodelist(codelistId)

  const terms = useListTerms(codelistId)

  return (
    <div className="flex flex-col gap-6">
      {codelist ? (
        <Button asChild variant="ghost" className="w-fit">
          <Link
            to="/standards/releases/$releaseId"
            params={{ releaseId: codelist.release_id }}
          >
            Back to release
          </Link>
        </Button>
      ) : (
        <Button asChild variant="ghost" className="w-fit">
          <Link to="/standards">Back to standards</Link>
        </Button>
      )}

      <PageHeader
        title={codelist ? `${codelist.code} — ${codelist.name}` : 'Codelist'}
      />

      {isError ? (
        <ErrorState error={error} resourceLabel="codelist" />
      ) : isLoading ? (
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-3">
          {Array.from({ length: 7 }).map((_, index) => (
            <Skeleton key={index} className="h-10 w-full" />
          ))}
        </div>
      ) : codelist ? (
        <DetailHeader
          fields={[
            { label: 'Code', value: codelist.code },
            { label: 'Name', value: codelist.name },
            {
              label: 'Submission value',
              value: codelist.submission_value ?? '—',
            },
            { label: 'Concept id', value: codelist.concept_id ?? '—' },
            {
              label: 'Preferred term',
              value: codelist.preferred_term ?? '—',
            },
            {
              label: 'Extensible',
              value: codelist.extensible ? 'Yes' : 'No',
            },
            {
              label: 'Synonyms',
              value: codelist.synonyms.join(', ') || '—',
            },
          ]}
        />
      ) : null}

      <ResourceTable
        columns={termColumns}
        rows={terms.data ?? []}
        getRowId={(row) => row.id}
        isLoading={terms.isLoading}
        isError={terms.isError}
        error={terms.error}
        resourceLabel="terms"
      />
    </div>
  )
}
