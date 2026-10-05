import { createFileRoute } from '@tanstack/react-router'
import { Boxes, FileCheck2, GitCompareArrows, Package } from 'lucide-react'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { useListStudies } from '@/api/generated/studies/studies'

export const Route = createFileRoute('/_app/')({
  component: DashboardPage,
})

function DashboardPage() {
  const { data, isLoading, isError } = useListStudies()
  const studyCount = data?.items.length ?? 0

  const stats = [
    {
      title: 'Studies',
      value: isLoading ? '—' : isError ? 'n/a' : String(studyCount),
      description: 'Visible to your principal',
      icon: Boxes,
    },
    {
      title: 'Validation runs',
      value: '—',
      description: 'Immutable validation snapshots',
      icon: FileCheck2,
    },
    {
      title: 'Reconciliations',
      value: '—',
      description: 'Cross-module comparisons',
      icon: GitCompareArrows,
    },
    {
      title: 'Packages',
      value: '—',
      description: 'Submission ZIPs assembled',
      icon: Package,
    },
  ]

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground text-sm">
          Overview of the Clinical Artifact Platform.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => (
          <Card key={stat.title}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                {stat.title}
              </CardTitle>
              <stat.icon className="text-muted-foreground size-4" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
              <p className="text-muted-foreground text-xs">
                {stat.description}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Getting started</CardTitle>
          <CardDescription>
            This UI talks to the FastAPI backend at <code>/api/v1</code>. The
            typed client and hooks are generated from the backend OpenAPI spec
            with Orval. Run <code>npm run api:sync</code> after backend changes
            to refresh them.
          </CardDescription>
        </CardHeader>
      </Card>
    </div>
  )
}
