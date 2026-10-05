import { createFileRoute } from '@tanstack/react-router'
import { formatDate } from '@/lib/utils'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCurrentStudy } from '@/components/study-provider'
import {
  useListPlatformRulePacks,
  useListRules,
  useListStudyRulePacks,
} from '@/api/generated/validation/validation'
import type { RulePackResponse, RuleResponse } from '@/api/generated/model'

export const Route = createFileRoute('/_app/validation')({
  component: ValidationPage,
})

const ruleColumns: ResourceColumn<RuleResponse>[] = [
  { key: 'rule_id', header: 'Rule id' },
  { key: 'version', header: 'Version' },
  { key: 'module_key', header: 'Module' },
  {
    key: 'default_severity',
    header: 'Severity',
    cell: (row) => <StatusBadge status={row.default_severity} />,
  },
  {
    key: 'mandatory',
    header: 'Mandatory',
    cell: (row) => (row.mandatory ? 'Yes' : 'No'),
  },
]

const rulePackColumns: ResourceColumn<RulePackResponse>[] = [
  { key: 'code', header: 'Code' },
  { key: 'name', header: 'Name' },
  {
    key: 'lifecycle',
    header: 'Lifecycle',
    cell: (row) => <StatusBadge status={row.lifecycle} />,
  },
  { key: 'revision', header: 'Revision' },
  {
    key: 'updated_at',
    header: 'Updated',
    cell: (row) => formatDate(row.updated_at),
  },
]

function RulesTab() {
  const { data, isLoading, isError, error } = useListRules()
  return (
    <ResourceTable
      columns={ruleColumns}
      rows={data ?? []}
      getRowId={(row) => row.id}
      isLoading={isLoading}
      isError={isError}
      error={error}
      resourceLabel="rules"
    />
  )
}

function PlatformRulePacksTab() {
  const { data, isLoading, isError, error } = useListPlatformRulePacks()
  return (
    <ResourceTable
      columns={rulePackColumns}
      rows={data ?? []}
      getRowId={(row) => row.id}
      isLoading={isLoading}
      isError={isError}
      error={error}
      resourceLabel="platform rule packs"
    />
  )
}

function StudyRulePacksTab() {
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListStudyRulePacks(
    currentStudyId ?? '',
    { query: { enabled: !!currentStudyId } },
  )
  return (
    <ResourceTable
      columns={rulePackColumns}
      rows={data ?? []}
      getRowId={(row) => row.id}
      isLoading={isLoading || studiesLoading}
      isError={isError}
      error={error}
      resourceLabel="study rule packs"
      emptyState={
        !studiesLoading && !currentStudyId ? (
          <EmptyState
            title="No study selected"
            description="Create a study first to view its rule packs."
          />
        ) : undefined
      }
    />
  )
}

function ValidationPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Validation"
        description="Platform rules, platform rule packs, and the current study's rule packs."
      />
      <Tabs defaultValue="rules">
        <TabsList>
          <TabsTrigger value="rules">Rules</TabsTrigger>
          <TabsTrigger value="platform">Platform rule packs</TabsTrigger>
          <TabsTrigger value="study">Study rule packs</TabsTrigger>
        </TabsList>
        <TabsContent value="rules">
          <RulesTab />
        </TabsContent>
        <TabsContent value="platform">
          <PlatformRulePacksTab />
        </TabsContent>
        <TabsContent value="study">
          <StudyRulePacksTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
