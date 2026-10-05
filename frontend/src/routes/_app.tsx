import { Outlet, createFileRoute, redirect } from '@tanstack/react-router'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/layout/app-sidebar'
import { Header } from '@/components/layout/header'
import { StudyProvider } from '@/components/study-provider'
import { isAuthenticated } from '@/lib/auth'

export const Route = createFileRoute('/_app')({
  beforeLoad: ({ location }) => {
    // Redirect to login when there is no stored bearer token. The Cognito
    // session is also restored in AuthProvider; this guard keeps protected
    // routes from rendering before a token exists.
    if (!isAuthenticated()) {
      throw redirect({
        to: '/login',
        search: { redirect: location.href },
      })
    }
  },
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
