import { createFileRoute } from '@tanstack/react-router'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { PageHeader } from '@/components/layout/page-header'
import { StatusBadge } from '@/components/data/status-badge'
import { useListStudies } from '@/api/generated/studies/studies'

export const Route = createFileRoute('/_app/studies')({
  component: StudiesPage,
})

function StudiesPage() {
  const { data, isLoading, isError, error } = useListStudies()

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Studies"
        description={
          <>
            Studies returned by <code>GET /api/v1/studies</code>.
          </>
        }
      />

      {isLoading && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      )}

      {isError && (
        <Card>
          <CardHeader>
            <CardTitle className="text-destructive">
              Could not load studies
            </CardTitle>
            <CardDescription>
              {error?.response?.status === 401
                ? 'Not authenticated. Set a bearer token (see auth.ts) to call the API.'
                : (error?.message ?? 'Request failed.')}
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {!isLoading && !isError && data && data.items.length === 0 && (
        <Card>
          <CardHeader>
            <CardTitle>No studies yet</CardTitle>
            <CardDescription>
              Create a study via <code>POST /api/v1/studies</code> and it will
              appear here.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {!isLoading && !isError && data && data.items.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.items.map((study) => (
            <Card key={study.id}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">{study.name}</CardTitle>
                  <StatusBadge status={study.status} />
                </div>
                <CardDescription>Code: {study.code}</CardDescription>
              </CardHeader>
              <CardContent className="text-muted-foreground text-xs">
                <div>Revision {study.revision}</div>
                <div>Created by {study.created_by}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
