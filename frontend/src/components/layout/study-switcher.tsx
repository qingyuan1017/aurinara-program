import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useCurrentStudy } from '@/components/study-provider'

export function StudySwitcher() {
  const { studies, currentStudyId, setCurrentStudyId, isLoading } =
    useCurrentStudy()

  if (isLoading) {
    return <Skeleton className="h-9 w-48" />
  }

  if (studies.length === 0) {
    return (
      <Select disabled>
        <SelectTrigger className="w-48 max-w-48">
          <SelectValue placeholder="No studies" />
        </SelectTrigger>
      </Select>
    )
  }

  return (
    <Select value={currentStudyId ?? undefined} onValueChange={setCurrentStudyId}>
      <SelectTrigger className="w-48 max-w-48">
        <SelectValue placeholder="Select study" />
      </SelectTrigger>
      <SelectContent>
        {studies.map((study) => (
          <SelectItem key={study.id} value={study.id}>
            <span className="truncate">
              {study.code} — {study.name}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
