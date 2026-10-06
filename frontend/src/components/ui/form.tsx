import * as React from 'react'
import { cn } from '@/lib/utils'
import { Label } from '@/components/ui/label'

/**
 * Dependency-free presentational form helpers (no react-hook-form). These give
 * the dialog a standard field scaffold while keeping the controlled-form
 * approach the read pass chose. Error state is passed in via props.
 */

function FormItem({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="form-item"
      className={cn('grid gap-2', className)}
      {...props}
    />
  )
}

function FormLabel({
  className,
  ...props
}: React.ComponentProps<typeof Label>) {
  return (
    <Label data-slot="form-label" className={className} {...props} />
  )
}

function FormControl({ ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="form-control" {...props} />
}

function FormDescription({
  className,
  ...props
}: React.ComponentProps<'p'>) {
  return (
    <p
      data-slot="form-description"
      className={cn('text-muted-foreground text-sm', className)}
      {...props}
    />
  )
}

function FormMessage({
  className,
  children,
  ...props
}: React.ComponentProps<'p'>) {
  if (!children) return null
  return (
    <p
      data-slot="form-message"
      className={cn('text-destructive text-sm font-medium', className)}
      {...props}
    >
      {children}
    </p>
  )
}

export { FormControl, FormDescription, FormItem, FormLabel, FormMessage }
