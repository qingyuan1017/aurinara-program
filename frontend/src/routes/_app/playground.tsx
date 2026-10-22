import { createFileRoute } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/page-header'
import { Playground } from '@/components/playground'

export const Route = createFileRoute('/_app/playground')({
  component: PlaygroundPage,
})

function PlaygroundPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Playground"
        description="Work with approved Aurinara agents. Every write requires your explicit confirmation."
      />
      <Playground />
    </div>
  )
}
