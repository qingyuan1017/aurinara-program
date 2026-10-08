import { Outlet, createFileRoute, redirect } from '@tanstack/react-router'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/layout/app-sidebar'
import { Header } from '@/components/layout/header'
import { StudyProvider } from '@/components/study-provider'
import { getAuthToken } from '@/lib/auth'

export const Route = createFileRoute('/_app')({
  // Auth guard: every authenticated-layout route requires a stored bearer
  // token. When none is present we bounce to /login before rendering, carrying
  // the originally requested path as the `redirect` search param so the login
  // flow returns the user there afterwards (login.tsx reads `redirect`). A 401
  // on a token that the server rejects is handled centrally in the axios
  // interceptor, which clears the token and sends the user back to /login.
  beforeLoad: ({ location }) => {
    if (getAuthToken() === null) {
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
