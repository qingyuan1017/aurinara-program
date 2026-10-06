import * as React from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { ListPlus, Pencil, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  ResourceFormDialog,
  type FieldDescriptor,
} from '@/components/forms/resource-form-dialog'
import { useCurrentStudy } from '@/components/study-provider'
import { useListReleases } from '@/api/generated/provider-catalogs/provider-catalogs'
import {
  getGetExtensionQueryKey,
  getListExtensionsQueryKey,
  getListExtensionTermsQueryKey,
  useCreateExtension,
  useCreateExtensionTerm,
  useListExtensions,
  useListExtensionTerms,
  usePatchExtensionTerm,
} from '@/api/generated/terminology/terminology'
import type {
  ExtensionCreate,
  ExtensionResponse,
  ExtensionTermPatch,
  ExtensionTermResponse,
  ExtensionTermWrite,
  TerminologyReleaseResponse,
} from '@/api/generated/model'
import { ifMatchRequest, jsonRequest } from '@/lib/requests'

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

const termColumns: ResourceColumn<ExtensionTermResponse>[] = [
  { key: 'code', header: 'Code' },
  { key: 'submission_value', header: 'Submission value' },
  { key: 'decode', header: 'Decode', className: 'max-w-sm truncate' },
  {
    key: 'preferred_term',
    header: 'Preferred term',
    cell: (row) => row.preferred_term ?? '—',
  },
]

const extensionFields: FieldDescriptor<ExtensionCreate>[] = [
  {
    name: 'code',
    label: 'Code',
    control: 'text',
    required: true,
    pattern: {
      re: /^[A-Za-z][A-Za-z0-9._-]{0,63}$/,
      message:
        'Code must start with a letter and use only letters, numbers, ., _ or - (max 64).',
    },
  },
  { name: 'name', label: 'Name', control: 'text', required: true, maxLength: 255 },
  { name: 'base_release_id', label: 'Base release id', control: 'text', required: true },
  {
    name: 'codelist_code',
    label: 'Codelist code',
    control: 'text',
    required: true,
    maxLength: 64,
  },
]

const termCreateFields: FieldDescriptor<ExtensionTermWrite>[] = [
  { name: 'code', label: 'Code', control: 'text', required: true, maxLength: 128 },
  {
    name: 'submission_value',
    label: 'Submission value',
    control: 'text',
    required: true,
    maxLength: 255,
  },
  {
    name: 'decode',
    label: 'Decode',
    control: 'textarea',
    required: true,
    maxLength: 1000,
  },
  { name: 'definition', label: 'Definition', control: 'textarea' },
  { name: 'preferred_term', label: 'Preferred term', control: 'text' },
  {
    name: 'synonyms',
    label: 'Synonyms',
    control: 'tags',
    helpText: 'Comma-separated synonyms.',
  },
]

const termEditFields: FieldDescriptor<ExtensionTermPatch>[] = [
  { name: 'submission_value', label: 'Submission value', control: 'text', maxLength: 255 },
  { name: 'decode', label: 'Decode', control: 'textarea', maxLength: 1000 },
  { name: 'definition', label: 'Definition', control: 'textarea' },
  { name: 'preferred_term', label: 'Preferred term', control: 'text' },
  {
    name: 'synonyms',
    label: 'Synonyms',
    control: 'tags',
    helpText: 'Comma-separated synonyms.',
  },
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

function TermsPanel({ extension }: { extension: ExtensionResponse }) {
  const qc = useQueryClient()
  const { currentStudyId } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListExtensionTerms(
    extension.id,
  )

  const [addOpen, setAddOpen] = React.useState(false)
  const [editing, setEditing] = React.useState<ExtensionTermResponse | null>(
    null,
  )

  // After each term write the extension's revision increments. Invalidate the
  // extension detail + list so the selected extension (and its revision) is
  // refetched before the next write, preventing a sequential 412.
  const invalidateAfterTermWrite = React.useCallback(() => {
    qc.invalidateQueries({
      queryKey: getListExtensionTermsQueryKey(extension.id),
    })
    qc.invalidateQueries({ queryKey: getGetExtensionQueryKey(extension.id) })
    qc.invalidateQueries({
      queryKey: getListExtensionsQueryKey(currentStudyId ?? undefined),
    })
  }, [qc, extension.id, currentStudyId])

  const addTerm = useCreateExtensionTerm({
    mutation: { onSuccess: invalidateAfterTermWrite },
    request: ifMatchRequest(extension.revision),
  })

  const patchTerm = usePatchExtensionTerm({
    mutation: { onSuccess: invalidateAfterTermWrite },
    request: ifMatchRequest(extension.revision),
  })

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">
          Terms for {extension.code}{' '}
          <span className="text-muted-foreground">
            (revision {extension.revision})
          </span>
        </h3>
        <Button size="sm" onClick={() => setAddOpen(true)}>
          <ListPlus /> Add term
        </Button>
      </div>
      <ResourceTable
        columns={termColumns}
        rows={data ?? []}
        getRowId={(row) => row.id}
        isLoading={isLoading}
        isError={isError}
        error={error}
        resourceLabel="extension terms"
        rowActions={(row) => (
          <Button size="sm" variant="outline" onClick={() => setEditing(row)}>
            <Pencil /> Edit
          </Button>
        )}
      />

      <ResourceFormDialog<ExtensionTermWrite>
        open={addOpen}
        onOpenChange={setAddOpen}
        title="Add term"
        description={`Add a term to extension ${extension.code}.`}
        fields={termCreateFields}
        initialValues={{ synonyms: [] }}
        submitLabel="Add term"
        successMessage="Term added."
        isSubmitting={addTerm.isPending}
        submitError={addTerm.error}
        onSubmit={(data) =>
          addTerm.mutateAsync({ extensionId: extension.id, data })
        }
      />

      <ResourceFormDialog<ExtensionTermPatch>
        open={!!editing}
        onOpenChange={(open) => {
          if (!open) setEditing(null)
        }}
        title="Edit term"
        description="Update term details."
        fields={termEditFields}
        initialValues={
          editing
            ? {
                submission_value: editing.submission_value,
                decode: editing.decode,
                definition: editing.definition,
                preferred_term: editing.preferred_term,
                synonyms: editing.synonyms,
              }
            : {}
        }
        submitLabel="Save changes"
        successMessage="Term updated."
        isSubmitting={patchTerm.isPending}
        submitError={patchTerm.error}
        onSubmit={(data) => patchTerm.mutateAsync({ termId: editing!.id, data })}
      />
    </div>
  )
}

function ExtensionsTab() {
  const qc = useQueryClient()
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListExtensions(
    currentStudyId ?? '',
    { query: { enabled: !!currentStudyId } },
  )

  const [createOpen, setCreateOpen] = React.useState(false)
  const [selectedId, setSelectedId] = React.useState<string | null>(null)

  const create = useCreateExtension({
    mutation: {
      onSuccess: () =>
        qc.invalidateQueries({
          queryKey: getListExtensionsQueryKey(currentStudyId ?? undefined),
        }),
    },
    request: jsonRequest(),
  })

  // Resolve the selected extension from the (possibly refetched) list so its
  // revision is always current for term-write If-Match headers.
  const selected =
    (data ?? []).find((extension) => extension.id === selectedId) ?? null

  return (
    <div className="flex flex-col gap-6">
      <div className="flex justify-end">
        <Button
          size="sm"
          disabled={!currentStudyId}
          onClick={() => setCreateOpen(true)}
        >
          <Plus /> New extension
        </Button>
      </div>
      <ResourceTable
        columns={extensionColumns}
        rows={data ?? []}
        getRowId={(row) => row.id}
        isLoading={isLoading || studiesLoading}
        isError={isError}
        error={error}
        resourceLabel="study extensions"
        onRowClick={(row) => setSelectedId(row.id)}
        emptyState={
          !studiesLoading && !currentStudyId ? (
            <EmptyState
              title="No study selected"
              description="Create a study first to view its terminology extensions."
            />
          ) : undefined
        }
        rowActions={(row) => (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setSelectedId(row.id)}
          >
            Manage terms
          </Button>
        )}
      />

      {selected && <TermsPanel key={selected.id} extension={selected} />}

      <ResourceFormDialog<ExtensionCreate>
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New extension"
        description="Create a study terminology extension."
        fields={extensionFields}
        initialValues={{}}
        submitLabel="Create extension"
        successMessage="Extension created."
        isSubmitting={create.isPending}
        submitError={create.error}
        onSubmit={(data) =>
          create.mutateAsync({ studyId: currentStudyId!, data })
        }
      />
    </div>
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
