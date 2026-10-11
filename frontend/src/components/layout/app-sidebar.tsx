import { Link, useRouterState } from '@tanstack/react-router'
import {
  Boxes,
  Database,
  FileText,
  FlaskConical,
  GitCompareArrows,
  LayoutDashboard,
  Library,
  ListChecks,
  BookMarked,
  type LucideIcon,
  MessageSquareText,
  Package,
  Plug,
  ShieldCheck,
  Table2,
} from 'lucide-react'
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from '@/components/ui/sidebar'

type NavItem = {
  title: string
  to: string
  icon: LucideIcon
}

type NavGroup = {
  label: string
  items: NavItem[]
}

// Navigation mirrors the backend modules exposed under /api/v1.
const navGroups: NavGroup[] = [
  {
    label: 'Overview',
    items: [{ title: 'Dashboard', to: '/', icon: LayoutDashboard }],
  },
  {
    label: 'Clinical modules',
    items: [
      { title: 'Studies', to: '/studies', icon: Boxes },
      { title: 'Reference', to: '/reference', icon: BookMarked },
      { title: 'Raw datasets', to: '/raw', icon: Database },
      { title: 'Documents', to: '/documents', icon: FileText },
      { title: 'SDTM', to: '/sdtm', icon: Table2 },
      { title: 'ADaM', to: '/adam', icon: FlaskConical },
      { title: 'TLF', to: '/tlf', icon: ListChecks },
    ],
  },
  {
    label: 'Shared services',
    items: [
      { title: 'Standards', to: '/standards', icon: Library },
      { title: 'Terminology', to: '/terminology', icon: Library },
      { title: 'Validation', to: '/validation', icon: ShieldCheck },
      { title: 'Reconciliation', to: '/reconciliation', icon: GitCompareArrows },
      { title: 'Review', to: '/review', icon: MessageSquareText },
      { title: 'Packaging', to: '/packaging', icon: Package },
      { title: 'Integrations', to: '/integrations', icon: Plug },
    ],
  },
]

export function AppSidebar() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })

  return (
    <Sidebar collapsible="icon" variant="inset">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link to="/">
                <div className="bg-sidebar-primary text-sidebar-primary-foreground flex aspect-square size-8 items-center justify-center rounded-lg shadow-sm">
                  <FlaskConical className="size-4" />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="font-display truncate text-base font-medium">Aurinara</span>
                  <span className="text-sidebar-primary truncate text-[10px] font-semibold tracking-[0.14em] uppercase">Clinical Artifacts</span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        {navGroups.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarMenu>
              {group.items.map((item) => {
                const isActive =
                  item.to === '/'
                    ? pathname === '/'
                    : pathname.startsWith(item.to)
                return (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton
                      asChild
                      isActive={isActive}
                      tooltip={item.title}
                    >
                      <Link to={item.to}>
                        <item.icon />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  )
}
