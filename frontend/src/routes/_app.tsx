import { Outlet, createFileRoute } from '@tanstack/react-router'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/layout/app-sidebar'
import { Header } from '@/components/layout/header'
import { StudyProvider } from '@/components/study-provider'

export const Route = createFileRoute('/_app')({
  // No auth redirect: the app shell stays visible when signed out so the
  // account menu (sign in / sign out) is always reachable. Data queries are
  // gated on isAuthenticated(), and unauthenticated screens show a
  // "sign in to continue" state instead of bouncing to /login.
  component: AppLayout,
})

function AppLayout() {
  return (
    <StudyProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset>
          <Header />
          <div className="flex flex-1 flex-col gap-4 p-4 md:p-6">
            <Outlet />
          </div>
        </SidebarInset>
      </SidebarProvider>
    </StudyProvider>
  )
}
