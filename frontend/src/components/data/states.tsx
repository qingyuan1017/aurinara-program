import * as React from 'react'
import type { AxiosError } from 'axios'
import type { LucideIcon } from 'lucide-react'
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { TableCell, TableRow } from '@/components/ui/table'

interface TableLoadingStateProps {
  columns: number
  rows?: number
}

export function TableLoadingState({ columns, rows = 5 }: TableLoadingStateProps) {
  return (
    <>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <TableRow key={rowIndex}>
          {Array.from({ length: columns }).map((_, cellIndex) => (
            <TableCell key={cellIndex}>
              <Skeleton className="h-4 w-full" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  )
}

interface ErrorStateProps {
  error: AxiosError | null
  resourceLabel: string
}

export function ErrorState({ error, resourceLabel }: ErrorStateProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-destructive">
          Could not load {resourceLabel}
        </CardTitle>
        <CardDescription>
          {error?.response?.status === 401
            ? 'Not authenticated. Set a bearer token (see auth.ts) to call the API.'
            : (error?.message ?? 'Request failed.')}
        </CardDescription>
      </CardHeader>
    </Card>
  )
}

interface EmptyStateProps {
  title: string
  description?: React.ReactNode
  icon?: LucideIcon
}

export function EmptyState({ title, description, icon: Icon }: EmptyStateProps) {
  return (
    <Card>
      <CardHeader>
        {Icon && <Icon className="text-muted-foreground size-6" />}
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
    </Card>
  )
}
