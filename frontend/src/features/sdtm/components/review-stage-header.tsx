import type { ReactNode } from 'react'

import { ShieldCheck } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

export interface ReviewStageMetric {
  label: string
  value: ReactNode
  tone?: 'default' | 'success' | 'warning' | 'danger'
}

interface ReviewStageHeaderProps {
  eyebrow: string
  title: string
  description: ReactNode
  status: string
  metrics?: readonly ReviewStageMetric[]
  actions?: ReactNode
}

const metricTone = {
  default: 'text-foreground',
  success: 'text-emerald-600 dark:text-emerald-400',
  warning: 'text-amber-600 dark:text-amber-400',
  danger: 'text-destructive',
} as const

/**
 * Shared visual contract for the artifact-review stages. It deliberately owns
 * presentation only: every action below it still uses the module's typed API.
 */
export function ReviewStageHeader({
  eyebrow,
  title,
  description,
  status,
  metrics = [],
  actions,
}: ReviewStageHeaderProps) {
  return (
    <Card className="overflow-hidden border-primary/25 bg-gradient-to-br from-primary/[0.08] via-card to-card">
      <CardHeader className="border-b bg-muted/20">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl space-y-2">
            <p className="text-primary text-xs font-bold uppercase tracking-[0.14em]">
              {eyebrow}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle>{title}</CardTitle>
              <Badge variant="outline" className="gap-1.5 bg-background/70">
                <ShieldCheck className="size-3.5 text-emerald-600" />
                {status}
              </Badge>
            </div>
            <CardDescription className="leading-5">{description}</CardDescription>
          </div>
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </div>
      </CardHeader>
      {metrics.length > 0 && (
        <CardContent className="grid gap-px bg-border p-0 sm:grid-cols-2 xl:grid-cols-4">
          {metrics.map((metric) => (
            <div key={metric.label} className="bg-card px-4 py-3">
              <p className="text-muted-foreground text-[10px] font-semibold uppercase tracking-wider">
                {metric.label}
              </p>
              <div
                className={`mt-1 truncate text-sm font-semibold ${metricTone[metric.tone ?? 'default']}`}
                title={typeof metric.value === 'string' ? metric.value : undefined}
              >
                {metric.value}
              </div>
            </div>
          ))}
        </CardContent>
      )}
    </Card>
  )
}
