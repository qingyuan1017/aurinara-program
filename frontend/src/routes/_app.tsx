import { Outlet, createFileRoute, redirect } from '@tanstack/react-router'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/layout/app-sidebar'
import { Header } from '@/components/layout/header'
import { StudyProvider } from '@/components/study-provider'
import { getAuthToken } from '@/lib/auth'
import { isOidcConfigured, restoreOidcSession } from '@/lib/oidc'

export const Route = createFileRoute('/_app')({
  // Auth guard: every authenticated-layout route requires a stored bearer
  // token. When none is present we bounce to /login before rendering, carrying
  // the originally requested path as the `redirect` search param so the login
  // flow returns the user there afterwards (login.tsx reads `redirect`). A 401
  // on a token that the server rejects is handled centrally in the axios
  // interceptor, which clears the token and sends the user back to /login.
  beforeLoad: async ({ location }) => {
    // The router starts before AuthProvider's effects run. Give oidc-client a
    // chance to restore its persisted user before deciding that the visitor is
    // unauthenticated; otherwise a refresh or a new route load briefly renders
    // the app and then bounces an already signed-in user back to /login.
    if (getAuthToken() === null && isOidcConfigured()) {
      await restoreOidcSession()
    }
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
          <main className="flex w-full min-w-0 flex-1 flex-col gap-5 px-4 py-6">
            <Outlet />
          </main>
        </SidebarInset>
      </SidebarProvider>
    </StudyProvider>
  )
}
