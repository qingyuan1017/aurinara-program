import { Search } from 'lucide-react'
import { Separator } from '@/components/ui/separator'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { Input } from '@/components/ui/input'
import { ThemeToggle } from '@/components/theme-toggle'
import { UserNav } from '@/components/layout/user-nav'
import { StudySwitcher } from '@/components/layout/study-switcher'

export function Header() {
  return (
    <header className="bg-background/95 supports-[backdrop-filter]:bg-background/60 sticky top-0 z-30 flex h-16 shrink-0 items-center gap-2 border-b backdrop-blur">
      <div className="flex w-full items-center gap-2 px-4">
        <SidebarTrigger className="-ml-1" />
        <Separator orientation="vertical" className="mr-2 h-4" />
        <div className="relative hidden w-full max-w-sm md:block">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
          <Input
            type="search"
            placeholder="Search studies, artifacts..."
            className="pl-8"
          />
        </div>
        <StudySwitcher />
        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          <UserNav />
        </div>
      </div>
    </header>
  )
}
