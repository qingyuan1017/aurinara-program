import * as React from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { BellPlus, Pencil, Plus } from 'lucide-react'
import { formatDate } from '@/lib/utils'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Button } from '@/components/ui/button'
import {
  ResourceFormDialog,
  type FieldDescriptor,
} from '@/components/forms/resource-form-dialog'
import { useCurrentStudy } from '@/components/study-provider'
import {
  getGetIntegrationQueryKey,
  getListIntegrationsQueryKey,
  getListSubscriptionsQueryKey,
  useCreateIntegration,
  useCreateSubscription,
  useListIntegrations,
  usePatchIntegration,
} from '@/api/generated/integrations/integrations'
import type {
  IntegrationPatch,
  IntegrationResponse,
  IntegrationWrite,
  SubscriptionWrite,
} from '@/api/generated/model'
import { ifMatchRequest, jsonRequest } from '@/lib/requests'

export const Route = createFileRoute('/_app/integrations')({
  component: IntegrationsPage,
})

const columns: ResourceColumn<IntegrationResponse>[] = [
  { key: 'integration_code', header: 'Code' },
  { key: 'display_name', header: 'Name' },
  { key: 'direction', header: 'Direction' },
  {
    key: 'status',
    header: 'Status',
    cell: (row) => <StatusBadge status={row.status} />,
  },
  { key: 'revision', header: 'Revision' },
  {
    key: 'updated_at',
    header: 'Updated',
    cell: (row) => formatDate(row.updated_at),
  },
]

const directionOptions = [
  { label: 'Inbound', value: 'inbound' },
  { label: 'Outbound', value: 'outbound' },
  { label: 'Bidirectional', value: 'bidirectional' },
]

const createFields: FieldDescriptor<IntegrationWrite>[] = [
  {
    name: 'integration_code',
    label: 'Integration code',
    control: 'text',
    required: true,
    pattern: {
      re: /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/,
      message:
        'Code must start with a letter or number and use only letters, numbers, ., _ or - (max 64).',
    },
  },
  { name: 'display_name', label: 'Display name', control: 'text', required: true },
  {
    name: 'direction',
    label: 'Direction',
    control: 'select',
    required: true,
    options: directionOptions,
  },
  { name: 'external_subject', label: 'External subject', control: 'text' },
  {
    name: 'allowed_modules',
    label: 'Allowed modules',
    control: 'tags',
    required: true,
    helpText: 'Comma-separated module codes.',
  },
]

const editFields: FieldDescriptor<IntegrationPatch>[] = [
  { name: 'display_name', label: 'Display name', control: 'text' },
  { name: 'external_subject', label: 'External subject', control: 'text' },
  {
    name: 'allowed_modules',
    label: 'Allowed modules',
    control: 'tags',
    helpText: 'Comma-separated module codes.',
  },
  {
    name: 'status',
    label: 'Status',
    control: 'select',
    options: [
      { label: 'Active', value: 'active' },
      { label: 'Retired', value: 'retired' },
    ],
  },
]

const subscriptionFields: FieldDescriptor<SubscriptionWrite>[] = [
  { name: 'callback_url', label: 'Callback URL', control: 'text', required: true },
  {
    name: 'event_types',
    label: 'Event types',
    control: 'tags',
    required: true,
    helpText: 'Comma-separated event type codes.',
  },
  {
    name: 'timeout_seconds',
    label: 'Timeout (seconds)',
    control: 'number',
    min: 1,
    max: 30,
  },
]

function IntegrationsPage() {
  const qc = useQueryClient()
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListIntegrations(
    currentStudyId ?? '',
    { query: { enabled: !!currentStudyId } },
  )

  const [createOpen, setCreateOpen] = React.useState(false)
  const [editing, setEditing] = React.useState<IntegrationResponse | null>(null)
  const [subscribing, setSubscribing] =
    React.useState<IntegrationResponse | null>(null)

  const listKey = getListIntegrationsQueryKey(currentStudyId ?? undefined)

  const create = useCreateIntegration({
    mutation: { onSuccess: () => qc.invalidateQueries({ queryKey: listKey }) },
    request: jsonRequest(),
  })

  const patch = usePatchIntegration({
    mutation: {
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: listKey })
        if (editing)
          qc.invalidateQueries({
            queryKey: getGetIntegrationQueryKey(editing.id),
          })
      },
    },
    request: editing ? ifMatchRequest(editing.revision) : undefined,
  })

  const subscribe = useCreateSubscription({
    mutation: {
      onSuccess: () => {
        if (subscribing)
          qc.invalidateQueries({
            queryKey: getListSubscriptionsQueryKey(subscribing.id),
          })
      },
    },
    request: jsonRequest(),
  })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Integrations"
        description={
          <>
            Integrations from{' '}
            <code>GET /api/v1/studies/{'{study_id}'}/integrations</code>.
          </>
        }
        actions={
          <Button
            size="sm"
            disabled={!currentStudyId}
            onClick={() => setCreateOpen(true)}
          >
            <Plus /> New integration
          </Button>
        }
      />
      <ResourceTable
        columns={columns}
        rows={data ?? []}
        getRowId={(row) => row.id}
        isLoading={isLoading || studiesLoading}
        isError={isError}
        error={error}
        resourceLabel="integrations"
        emptyState={
          !studiesLoading && !currentStudyId ? (
            <EmptyState
              title="No study selected"
              description="Create a study first to view its integrations."
            />
          ) : undefined
        }
        rowActions={(row) => (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => setEditing(row)}>
              <Pencil /> Edit
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setSubscribing(row)}
            >
              <BellPlus /> Subscription
            </Button>
          </div>
        )}
      />

      <ResourceFormDialog<IntegrationWrite>
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New integration"
        description="Register an external integration for this study."
        fields={createFields}
        initialValues={{ allowed_modules: [] }}
        submitLabel="Create integration"
        successMessage="Integration created."
        isSubmitting={create.isPending}
        submitError={create.error}
        onSubmit={(data) =>
          create.mutateAsync({ studyId: currentStudyId!, data })
        }
      />

      <ResourceFormDialog<IntegrationPatch>
        open={!!editing}
        onOpenChange={(open) => {
          if (!open) setEditing(null)
        }}
        title="Edit integration"
        description="Update integration metadata."
        fields={editFields}
        initialValues={
          editing
            ? {
                display_name: editing.display_name,
                external_subject: editing.external_subject,
                allowed_modules: editing.allowed_modules,
                status: editing.status as IntegrationPatch['status'],
              }
            : {}
        }
        submitLabel="Save changes"
        successMessage="Integration updated."
        isSubmitting={patch.isPending}
        submitError={patch.error}
        onSubmit={(data) =>
          patch.mutateAsync({ integrationId: editing!.id, data })
        }
      />

      <ResourceFormDialog<SubscriptionWrite>
        open={!!subscribing}
        onOpenChange={(open) => {
          if (!open) setSubscribing(null)
        }}
        title="New subscription"
        description={
          subscribing
            ? `Add a webhook subscription to "${subscribing.display_name}".`
            : undefined
        }
        fields={subscriptionFields}
        initialValues={{ event_types: [] }}
        submitLabel="Create subscription"
        successMessage="Subscription created."
        isSubmitting={subscribe.isPending}
        submitError={subscribe.error}
        onSubmit={(data) =>
          subscribe.mutateAsync({ integrationId: subscribing!.id, data })
        }
      />
    </div>
  )
}
