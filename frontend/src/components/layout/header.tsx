import { useRouterState } from '@tanstack/react-router'
import { Separator } from '@/components/ui/separator'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { ThemeToggle } from '@/components/theme-toggle'

const routeTitles: readonly [string, string][] = [
  ['/repository', 'Repository'], ['/studies', 'Studies'], ['/reference', 'Reference'],
  ['/raw', 'Raw datasets'], ['/documents', 'Documents'], ['/sdtm', 'SDTM'],
  ['/adam', 'ADaM'], ['/tlf', 'TLF'], ['/standards', 'Standards'],
  ['/terminology', 'Terminology'], ['/validation', 'Validation'],
  ['/reconciliation', 'Reconciliation'], ['/review', 'Review'],
  ['/packaging', 'Packaging'], ['/integrations', 'Integrations'],
]

export function Header() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const pageTitle = pathname === '/' ? 'Dashboard' : routeTitles.find(([prefix]) => pathname.startsWith(prefix))?.[1] ?? 'Workspace'

  return (
    <header className="bg-background/85 sticky top-0 z-50 flex h-16 shrink-0 items-center gap-3 border-b p-4 backdrop-blur-xl sm:gap-4">
      <SidebarTrigger variant="outline" className="max-md:scale-125" />
      <Separator orientation="vertical" className="h-6" />
      <div className="min-w-0 flex-1 leading-tight">
        <span className="text-muted-foreground block truncate text-[10px] font-semibold uppercase tracking-[0.14em]">Clinical artifacts</span>
        <span className="block truncate text-sm font-semibold text-foreground">{pageTitle}</span>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <ThemeToggle />
      </div>
    </header>
  )
}
