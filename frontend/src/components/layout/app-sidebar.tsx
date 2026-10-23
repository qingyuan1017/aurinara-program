import { forwardRef, useEffect, useState, type AnchorHTMLAttributes, type ReactNode } from 'react'
import { Link, useNavigate, useRouterState } from '@tanstack/react-router'
import {
  BookMarked,
  Bot,
  Boxes,
  Check,
  ChevronsUpDown,
  Database,
  FileText,
  FlaskConical,
  FolderKanban,
  GitCompareArrows,
  LayoutDashboard,
  Library,
  ListChecks,
  LogOut,
  Menu,
  MessageSquareText,
  Package,
  PanelsTopLeft,
  Plug,
  ShieldCheck,
  SquareTerminal,
  Table2,
  type LucideIcon,
} from 'lucide-react'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from '@/components/ui/sidebar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useCurrentStudy } from '@/components/study-context'
import { useAuth } from '@/components/auth-provider'
import {
  WORKSPACE_MODULES,
  resolveActiveTab,
  resolveDetailNavigation,
  resolveWorkspaceModule,
  type AdamTab,
  type ClinicalModuleKey,
  type DetailNavigation,
  type DocumentTab,
  type NavigationTab,
  type RawTab,
  type SdtmTab,
  type TlfTab,
  type WorkspaceModule,
} from '@/lib/clinical-navigation'
import { cn } from '@/lib/utils'

type NavItem = {
  title: string
  to:
    | '/'
    | '/repository'
    | '/studies'
    | '/standards'
    | '/terminology'
    | '/validation'
    | '/reconciliation'
    | '/review'
    | '/packaging'
    | '/integrations'
    | '/playground'
    | '/workspace'
  icon: LucideIcon
}

type NavGroup = {
  label: string
  items: readonly NavItem[]
}

const portfolioNavGroups: readonly NavGroup[] = [
  {
    label: 'Portfolio',
    items: [
      { title: 'Dashboard', to: '/', icon: LayoutDashboard },
      { title: 'Repository', to: '/repository', icon: FolderKanban },
      { title: 'Studies', to: '/studies', icon: Boxes },
    ],
  },
  {
    label: 'Shared services',
    items: [
      { title: 'Standards', to: '/standards', icon: Library },
      { title: 'Terminology', to: '/terminology', icon: BookMarked },
      { title: 'Validation', to: '/validation', icon: ShieldCheck },
      { title: 'Reconciliation', to: '/reconciliation', icon: GitCompareArrows },
      { title: 'Review', to: '/review', icon: MessageSquareText },
      { title: 'Packaging', to: '/packaging', icon: Package },
      { title: 'Integrations', to: '/integrations', icon: Plug },
      { title: 'Playground', to: '/playground', icon: Bot },
      { title: 'Workspace', to: '/workspace', icon: SquareTerminal },
    ],
  },
]

const moduleIcons: Record<ClinicalModuleKey, LucideIcon> = {
  reference: BookMarked,
  raw: Database,
  documents: FileText,
  sdtm: Table2,
  adam: FlaskConical,
  tlf: ListChecks,
}

const moduleHomeLabels: Record<ClinicalModuleKey, string> = {
  reference: 'Reference data',
  raw: 'Workbenches',
  documents: 'Documents',
  sdtm: 'Workbenches',
  adam: 'Workbenches',
  tlf: 'Workbenches',
}

const MODULE_KEY = 'aurinara.currentModule'

function readStoredModule(): ClinicalModuleKey {
  try {
    const stored = localStorage.getItem(MODULE_KEY)
    const module = WORKSPACE_MODULES.find((item) => item.key === stored)
    if (module) return module.key
  } catch {
    // Fall back to the first module when storage is unavailable.
  }
  return WORKSPACE_MODULES[0].key
}

function writeStoredModule(module: ClinicalModuleKey): void {
  try {
    localStorage.setItem(MODULE_KEY, module)
  } catch {
    // Navigation still works when storage is unavailable.
  }
}

function AppTitle() {
  const { state, toggleSidebar, setOpenMobile } = useSidebar()

  return (
    <div className="flex h-12 items-center gap-0 rounded-md p-2 group-data-[collapsible=icon]:size-8 group-data-[collapsible=icon]:p-0">
      {state === 'expanded' && (
        <Link
          to="/"
          onClick={() => setOpenMobile(false)}
          className="grid min-w-0 flex-1 text-start text-sm leading-tight"
        >
          <span className="truncate font-bold">Aurinara</span>
          <span className="text-muted-foreground truncate text-[11px]">Clinical Artifact Platform</span>
        </Link>
      )}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="aspect-square size-8 shrink-0"
        onClick={toggleSidebar}
        aria-label={state === 'expanded' ? 'Collapse sidebar' : 'Expand sidebar'}
        title={state === 'expanded' ? 'Collapse sidebar' : 'Expand sidebar'}
      >
        <Menu />
      </Button>
    </div>
  )
}

function navigateToModule(
  navigate: ReturnType<typeof useNavigate>,
  module: WorkspaceModule,
) {
  switch (module.landingPath) {
    case '/reference':
      navigate({ to: '/reference' })
      return
    case '/raw':
      navigate({ to: '/raw' })
      return
    case '/documents':
      navigate({ to: '/documents' })
      return
    case '/sdtm':
      navigate({ to: '/sdtm' })
      return
    case '/adam':
      navigate({ to: '/adam' })
      return
    case '/tlf':
      navigate({ to: '/tlf' })
  }
}

function ModuleSwitcher({
  activeModule,
  onSelectModule,
}: {
  activeModule: ClinicalModuleKey
  onSelectModule: (module: WorkspaceModule) => void
}) {
  const { isMobile, setOpenMobile } = useSidebar()
  const active = WORKSPACE_MODULES.find((module) => module.key === activeModule) ?? WORKSPACE_MODULES[0]
  const ActiveIcon = moduleIcons[active.key]

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
              aria-label="Select module"
            >
              <span className="bg-sidebar-primary text-sidebar-primary-foreground flex aspect-square size-8 items-center justify-center rounded-lg">
                <ActiveIcon className="size-4" />
              </span>
              <span className="grid min-w-0 flex-1 text-start text-sm leading-tight">
                <span className="truncate font-semibold">{active.label}</span>
                <span className="text-muted-foreground truncate text-xs">{active.description}</span>
              </span>
              <ChevronsUpDown className="ms-auto" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="min-w-60 rounded-lg"
            align="start"
            side={isMobile ? 'bottom' : 'right'}
            sideOffset={4}
          >
            <DropdownMenuLabel className="text-muted-foreground text-xs">Clinical modules</DropdownMenuLabel>
            {WORKSPACE_MODULES.map((module) => {
              const Icon = moduleIcons[module.key]
              return (
                <DropdownMenuItem
                  key={module.key}
                  className="gap-2 p-2"
                  onSelect={() => {
                    onSelectModule(module)
                    setOpenMobile(false)
                  }}
                >
                  <span className="flex size-6 items-center justify-center rounded-sm border">
                    <Icon className="size-4 shrink-0" />
                  </span>
                  <span className="grid min-w-0 flex-1 leading-tight">
                    <span className="truncate text-sm">{module.label}</span>
                    <span className="text-muted-foreground truncate text-xs">{module.description}</span>
                  </span>
                  <Check className={cn('ms-auto size-4', module.key === active.key ? 'opacity-100' : 'opacity-0')} />
                </DropdownMenuItem>
              )
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}

function SidebarStudySwitcher({
  activeModule,
  isPortfolio,
}: {
  activeModule: WorkspaceModule
  isPortfolio: boolean
}) {
  const { studies, currentStudyId, setCurrentStudyId, isLoading } = useCurrentStudy()
  const navigate = useNavigate()
  const { isMobile, setOpenMobile } = useSidebar()
  const activeStudy = studies.find((study) => study.id === currentStudyId)
  const label = isPortfolio
    ? 'Portfolio'
    : activeStudy?.name ?? (isLoading ? 'Loading studies…' : 'Select study')
  const subLabel = isPortfolio ? 'All studies' : activeStudy?.code ?? 'Study context'
  const ScopeIcon = isPortfolio ? PanelsTopLeft : FlaskConical

  function selectStudy(studyId: string) {
    setCurrentStudyId(studyId)
    if (isPortfolio) navigateToModule(navigate, activeModule)
    setOpenMobile(false)
  }

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
              aria-label="Select study"
            >
              <span className="bg-muted flex aspect-square size-8 items-center justify-center rounded-lg">
                <ScopeIcon className="size-4" />
              </span>
              <span className="grid min-w-0 flex-1 text-start text-sm leading-tight">
                <span className="truncate font-semibold">{label}</span>
                <span className="text-muted-foreground truncate text-xs">{subLabel}</span>
              </span>
              <ChevronsUpDown className="ms-auto" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="min-w-60 rounded-lg"
            align="start"
            side={isMobile ? 'bottom' : 'right'}
            sideOffset={4}
          >
            <DropdownMenuLabel className="text-muted-foreground text-xs">Study scope</DropdownMenuLabel>
            <DropdownMenuItem
              className="gap-2 p-2"
              onSelect={() => {
                navigate({ to: '/' })
                setOpenMobile(false)
              }}
            >
              <span className="flex size-6 items-center justify-center rounded-sm border">
                <PanelsTopLeft className="size-4 shrink-0" />
              </span>
              <span className="grid min-w-0 flex-1 leading-tight">
                <span className="truncate text-sm">Portfolio</span>
                <span className="text-muted-foreground truncate text-xs">All studies</span>
              </span>
              <Check className={cn('ms-auto size-4', isPortfolio ? 'opacity-100' : 'opacity-0')} />
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {studies.length > 0 ? (
              studies.map((study) => (
                <DropdownMenuItem
                  key={study.id}
                  onSelect={() => selectStudy(study.id)}
                  className="gap-2 p-2"
                >
                  <span className="flex size-6 items-center justify-center rounded-sm border">
                    <FlaskConical className="size-4 shrink-0" />
                  </span>
                  <span className="grid min-w-0 flex-1 leading-tight">
                    <span className="truncate text-sm">{study.name}</span>
                    <span className="text-muted-foreground truncate text-xs">{study.code}</span>
                  </span>
                  <Check className={cn('ms-auto size-4', !isPortfolio && study.id === currentStudyId ? 'opacity-100' : 'opacity-0')} />
                </DropdownMenuItem>
              ))
            ) : (
              <div className="text-muted-foreground px-2 py-1.5 text-sm">No studies yet</div>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}

function SidebarUser() {
  const navigate = useNavigate()
  const { user, signOut } = useAuth()
  const { isMobile } = useSidebar()
  const email = user?.email ?? 'Signed in'
  const displayName = user
    ? `${user.firstName ?? ''} ${user.lastName ?? ''}`.trim() ||
      user.name?.trim() ||
      user.email ||
      'Account'
    : 'Account'
  const initials = displayName.slice(0, 2).toUpperCase()

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
              aria-label={`Open user menu for ${displayName}`}
            >
              <span className="bg-muted text-muted-foreground flex size-8 items-center justify-center rounded-lg text-xs font-semibold">{initials}</span>
              <span className="grid min-w-0 flex-1 text-start text-sm leading-tight">
                <span className="truncate font-semibold">{displayName}</span>
                <span className="text-muted-foreground truncate text-xs">{email}</span>
              </span>
              <ChevronsUpDown className="ms-auto size-4" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="min-w-56 rounded-lg" side={isMobile ? 'bottom' : 'right'} align="end" sideOffset={4}>
            <DropdownMenuLabel className="font-normal">
              <span className="grid text-start text-sm leading-tight">
                <span className="truncate font-semibold">{displayName}</span>
                <span className="text-muted-foreground truncate text-xs">{email}</span>
              </span>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => { signOut(); navigate({ to: '/login', search: { redirect: undefined } }) }}>
              <LogOut /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}

function PortfolioNavigation({ pathname }: { pathname: string }) {
  return portfolioNavGroups.map((group) => (
    <SidebarGroup key={group.label}>
      <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
      <SidebarMenu>
        {group.items.map((item) => (
          <SidebarMenuItem key={item.to}>
            <SidebarMenuButton
              asChild
              isActive={item.to === '/' ? pathname === '/' : pathname.startsWith(item.to)}
              tooltip={item.title}
            >
              <Link to={item.to}>
                <item.icon />
                <span>{item.title}</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  ))
}

const DetailTabLink = forwardRef<HTMLAnchorElement, AnchorHTMLAttributes<HTMLAnchorElement> & {
  detail: DetailNavigation
  tab: NavigationTab
  children: ReactNode
}>(function DetailTabLink({ detail, tab, children, ...props }, ref) {
  switch (detail.module) {
    case 'raw':
      return <Link ref={ref} to="/raw/$rawId" params={{ rawId: detail.id }} search={{ tab: tab.value as RawTab }} {...props}>{children}</Link>
    case 'documents':
      return <Link ref={ref} to="/documents/$documentId" params={{ documentId: detail.id }} search={{ tab: tab.value as DocumentTab }} {...props}>{children}</Link>
    case 'sdtm':
      return <Link ref={ref} to="/sdtm/$sdtmId" params={{ sdtmId: detail.id }} search={{ tab: tab.value as SdtmTab }} {...props}>{children}</Link>
    case 'adam':
      return <Link ref={ref} to="/adam/$adamId" params={{ adamId: detail.id }} search={{ tab: tab.value as AdamTab }} {...props}>{children}</Link>
    case 'tlf':
      return <Link ref={ref} to="/tlf/$tlfId" params={{ tlfId: detail.id }} search={{ tab: tab.value as TlfTab }} {...props}>{children}</Link>
  }
})

function ModuleNavigation({
  module,
  pathname,
  requestedTab,
}: {
  module: ClinicalModuleKey
  pathname: string
  requestedTab: unknown
}) {
  const workspace = WORKSPACE_MODULES.find((item) => item.key === module)!
  const Icon = moduleIcons[module]
  const detail = resolveDetailNavigation(pathname)
  const activeTab = resolveActiveTab(detail, requestedTab)

  return (
    <>
      <SidebarGroup>
        <SidebarGroupLabel>{workspace.label}</SidebarGroupLabel>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              isActive={pathname === workspace.landingPath}
              tooltip={moduleHomeLabels[module]}
            >
              <Link to={workspace.landingPath}>
                <Icon />
                <span>{moduleHomeLabels[module]}</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarGroup>

      {detail && detail.module === module && (
        <SidebarGroup>
          <SidebarGroupLabel>{detail.label}</SidebarGroupLabel>
          <SidebarMenu className="border-sidebar-border ms-3 w-[calc(100%-0.75rem)] border-s ps-2">
            {detail.tabs.map((tab) => (
              <SidebarMenuItem key={tab.value}>
                <SidebarMenuButton asChild isActive={activeTab === tab.value} tooltip={tab.label} size="sm">
                  <DetailTabLink detail={detail} tab={tab}>
                    <span>{tab.label}</span>
                  </DetailTabLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>
      )}
    </>
  )
}

export function AppSidebar() {
  const location = useRouterState({ select: (state) => state.location })
  const navigate = useNavigate()
  const pathname = location.pathname
  const requestedTab = (location.search as { tab?: unknown }).tab
  const activeScope = resolveWorkspaceModule(pathname)
  const routeModule = WORKSPACE_MODULES.find((module) => module.key === activeScope)
  const [selectedModuleKey, setSelectedModuleKey] = useState<ClinicalModuleKey>(
    () => routeModule?.key ?? readStoredModule(),
  )
  const activeModule = WORKSPACE_MODULES.find((module) => module.key === selectedModuleKey) ?? WORKSPACE_MODULES[0]

  useEffect(() => {
    if (!routeModule) return
    setSelectedModuleKey(routeModule.key)
    writeStoredModule(routeModule.key)
  }, [routeModule])

  function selectModule(module: WorkspaceModule) {
    setSelectedModuleKey(module.key)
    writeStoredModule(module.key)
    if (activeScope !== 'portfolio') navigateToModule(navigate, module)
  }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <AppTitle />
        <ModuleSwitcher activeModule={activeModule.key} onSelectModule={selectModule} />
        <SidebarStudySwitcher activeModule={activeModule} isPortfolio={activeScope === 'portfolio'} />
      </SidebarHeader>
      <SidebarContent>
        <nav aria-label={`${activeScope === 'portfolio' ? 'Portfolio' : activeModule.label} navigation`}>
          {activeScope === 'portfolio' ? (
            <PortfolioNavigation pathname={pathname} />
          ) : (
            <ModuleNavigation module={activeModule.key} pathname={pathname} requestedTab={requestedTab} />
          )}
        </nav>
      </SidebarContent>
      <SidebarFooter><SidebarUser /></SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
