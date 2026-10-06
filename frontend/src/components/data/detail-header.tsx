import * as React from 'react'
import { Card, CardContent } from '@/components/ui/card'

export interface DetailField {
  label: string
  value: React.ReactNode
}

export interface DetailHeaderProps {
  fields: DetailField[]
}

export function DetailHeader({ fields }: DetailHeaderProps) {
  return (
    <Card>
      <CardContent>
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-3">
          {fields.map((field) => (
            <div key={field.label}>
              <div className="text-muted-foreground text-xs">{field.label}</div>
              <div className="text-sm">{field.value}</div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
