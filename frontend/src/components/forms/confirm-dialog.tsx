import * as React from 'react'
import type { AxiosError } from 'axios'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { parseProblem, stalenessAlert } from '@/lib/problems'

export interface ConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: React.ReactNode
  confirmLabel?: string
  onConfirm: () => Promise<unknown>
  isPending: boolean
  error: AxiosError | null
  destructive?: boolean
  successMessage?: string
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = 'Confirm',
  onConfirm,
  isPending,
  error,
  destructive,
}: ConfirmDialogProps) {
  const [alert, setAlert] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (open) setAlert(null)
  }, [open])

  async function handleConfirm() {
    setAlert(null)
    try {
      await onConfirm()
      onOpenChange(false)
    } catch (err) {
      const axiosError = err as AxiosError
      setAlert(
        stalenessAlert(axiosError) ??
          parseProblem(axiosError).detail ??
          axiosError.message ??
          'Request failed.',
      )
    }
  }

  const message = alert ?? (error ? stalenessAlert(error) : null)

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!isPending) onOpenChange(next)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>

        {message && (
          <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm">
            {message}
          </div>
        )}

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={isPending}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant={destructive ? 'destructive' : 'default'}
            disabled={isPending}
            onClick={handleConfirm}
          >
            {isPending && <Loader2 className="animate-spin" />}
            {isPending ? 'Working…' : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
