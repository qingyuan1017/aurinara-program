import { Badge } from '@/components/ui/badge'

type BadgeVariant = 'default' | 'secondary' | 'outline' | 'destructive'

function statusVariant(status: string): BadgeVariant {
  switch (status.toLowerCase()) {
    case 'active':
    case 'approved':
      return 'default'
    case 'archived':
    case 'retired':
      return 'secondary'
    case 'draft':
    case 'pending':
      return 'outline'
    case 'failed':
    case 'error':
      return 'destructive'
    default:
      return 'secondary'
  }
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge variant={statusVariant(status)}>{status}</Badge>
}
