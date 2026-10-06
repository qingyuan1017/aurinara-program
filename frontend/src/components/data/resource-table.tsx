import * as React from 'react'
import type { AxiosError } from 'axios'
import { cn } from '@/lib/utils'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { EmptyState, ErrorState, TableLoadingState } from '@/components/data/states'

export interface ResourceColumn<T> {
  key: string
  header: string
  cell?: (row: T) => React.ReactNode
  className?: string
}

export interface ResourceTableProps<T> {
  columns: ResourceColumn<T>[]
  rows: T[] | undefined
  getRowId: (row: T) => string
  isLoading: boolean
  isError: boolean
  error: AxiosError | null
  resourceLabel: string
  emptyState?: React.ReactNode
  onRowClick?: (row: T) => void
  rowActions?: (row: T) => React.ReactNode
}

export function ResourceTable<T>({
  columns,
  rows,
  getRowId,
  isLoading,
  isError,
  error,
  resourceLabel,
  emptyState,
  onRowClick,
  rowActions,
}: ResourceTableProps<T>) {
  if (isError) {
    return <ErrorState error={error} resourceLabel={resourceLabel} />
  }

  const header = (
    <TableHeader>
      <TableRow>
        {columns.map((column) => (
          <TableHead key={column.key} className={column.className}>
            {column.header}
          </TableHead>
        ))}
        {rowActions && (
          <TableHead className="w-[1%] text-right">
            <span className="sr-only">Actions</span>
          </TableHead>
        )}
      </TableRow>
    </TableHeader>
  )

  if (isLoading) {
    return (
      <div className="rounded-md border">
        <Table>
          {header}
          <TableBody>
            <TableLoadingState
              columns={columns.length + (rowActions ? 1 : 0)}
            />
          </TableBody>
        </Table>
      </div>
    )
  }

  const data = rows ?? []

  if (data.length === 0) {
    return (
      <>
        {emptyState ?? (
          <EmptyState
            title={`No ${resourceLabel} yet`}
            description={`No ${resourceLabel} to display.`}
          />
        )}
      </>
    )
  }

  return (
    <div className="rounded-md border">
      <Table>
        {header}
        <TableBody>
          {data.map((row) => (
            <TableRow
              key={getRowId(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={cn(onRowClick && 'cursor-pointer hover:bg-muted/50')}
            >
              {columns.map((column) => (
                <TableCell key={column.key} className={column.className}>
                  {column.cell?.(row) ??
                    String(
                      (row as Record<string, unknown>)[column.key] ?? '—',
                    )}
                </TableCell>
              ))}
              {rowActions && (
                <TableCell className="text-right">{rowActions(row)}</TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
