// @vitest-environment jsdom
import { forwardRef, type AnchorHTMLAttributes, type ReactNode } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { installJsdomHarness } from '@/test/jsdom-harness'
import { SidebarProvider } from '@/components/ui/sidebar'

const routerState = vi.hoisted(() => ({
  location: { pathname: '/', search: {} as Record<string, unknown> },
}))
const navigateSpy = vi.hoisted(() => vi.fn())
const setCurrentStudyIdSpy = vi.hoisted(() => vi.fn())
const signOutSpy = vi.hoisted(() => vi.fn())

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => navigateSpy,
  useRouterState: ({ select }: { select: (state: typeof routerState) => unknown }) =>
    select(routerState),
  Link: forwardRef<
    HTMLAnchorElement,
    AnchorHTMLAttributes<HTMLAnchorElement> & {
      children?: ReactNode
      to: string
      params?: Record<string, string>
      search?: Record<string, unknown>
    }
  >(({ children, to, params, search, ...props }, ref) => {
    let href = to
    for (const [key, value] of Object.entries(params ?? {})) {
      href = href.replace(`$${key}`, value)
    }
    const query = new URLSearchParams(
      Object.entries(search ?? {}).map(([key, value]) => [key, String(value)]),
    ).toString()
    return <a ref={ref} href={`${href}${query ? `?${query}` : ''}`} {...props}>{children}</a>
  }),
}))

vi.mock('@/components/study-context', () => ({
  useCurrentStudy: () => ({
    studies: [{ id: 'study-1', code: 'ABC-001', name: 'Example study' }],
    currentStudyId: 'study-1',
    setCurrentStudyId: setCurrentStudyIdSpy,
    isLoading: false,
  }),
}))

vi.mock('@/components/auth-provider', () => ({
  useAuth: () => ({
    user: {
      username: '24890137',
      email: 'reviewer@example.test',
      firstName: 'EDC',
      lastName: 'User',
    },
    signOut: signOutSpy,
  }),
}))

vi.mock('@/hooks/use-mobile', () => ({ useIsMobile: () => false }))

import { AppSidebar } from './app-sidebar'

beforeAll(() => installJsdomHarness())

describe('AppSidebar navigation hierarchy', () => {
  beforeEach(() => {
    routerState.location = { pathname: '/', search: {} }
    navigateSpy.mockReset()
    setCurrentStudyIdSpy.mockReset()
    signOutSpy.mockReset()
    localStorage.removeItem('aurinara.currentModule')
  })

  it('shows the portfolio services and keeps selectors above navigation', () => {
    render(<SidebarProvider><AppSidebar /></SidebarProvider>)

    expect(screen.getByRole('button', { name: 'Select module' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Select study' })).toBeTruthy()
    const navigation = screen.getByRole('navigation', { name: 'Portfolio navigation' })
    expect(navigation.textContent).toContain('Dashboard')
    expect(navigation.textContent).toContain('Repository')
    expect(navigation.textContent).toContain('Workspace')
    expect(navigation.textContent).toContain('Standards')
    expect(navigation.textContent).toContain('Integrations')
    expect(navigation.textContent).not.toContain('SDTM')
  })

  it('keeps the selected clinical module while Portfolio is the study scope', async () => {
    const user = userEvent.setup()
    render(<SidebarProvider><AppSidebar /></SidebarProvider>)

    await user.click(screen.getByRole('button', { name: 'Select module' }))
    expect(screen.queryByRole('menuitem', { name: /Portfolio/ })).toBeNull()
    await user.click(await screen.findByRole('menuitem', { name: /SDTM/ }))

    expect(screen.getByRole('button', { name: 'Select module' }).textContent).toContain('SDTM')
    expect(navigateSpy).not.toHaveBeenCalled()
  })

  it('enters a study in the clinical module selected at Portfolio scope', async () => {
    const user = userEvent.setup()
    render(<SidebarProvider><AppSidebar /></SidebarProvider>)

    await user.click(screen.getByRole('button', { name: 'Select module' }))
    await user.click(await screen.findByRole('menuitem', { name: /SDTM/ }))
    await user.click(screen.getByRole('button', { name: 'Select study' }))
    expect(await screen.findByRole('menuitem', { name: /Portfolio/ })).toBeTruthy()
    await user.click(screen.getByRole('menuitem', { name: /Example study/ }))

    expect(setCurrentStudyIdSpy).toHaveBeenCalledWith('study-1')
    expect(navigateSpy).toHaveBeenCalledWith({ to: '/sdtm' })
  })

  it('switches from a study module to Portfolio through the study selector', async () => {
    routerState.location = { pathname: '/sdtm', search: {} }
    const user = userEvent.setup()
    render(<SidebarProvider><AppSidebar /></SidebarProvider>)

    await user.click(screen.getByRole('button', { name: 'Select study' }))
    await user.click(await screen.findByRole('menuitem', { name: /Portfolio/ }))

    expect(navigateSpy).toHaveBeenCalledWith({ to: '/' })
  })

  it('navigates immediately when switching modules within a study', async () => {
    routerState.location = { pathname: '/raw', search: {} }
    const user = userEvent.setup()
    render(<SidebarProvider><AppSidebar /></SidebarProvider>)

    await user.click(screen.getByRole('button', { name: 'Select module' }))
    await user.click(await screen.findByRole('menuitem', { name: /SDTM/ }))

    expect(navigateSpy).toHaveBeenCalledWith({ to: '/sdtm' })
  })

  it('shows the active workbench tab in module navigation', () => {
    routerState.location = {
      pathname: '/sdtm/workbench-1',
      search: { tab: 'define' },
    }
    render(<SidebarProvider><AppSidebar /></SidebarProvider>)

    const navigation = screen.getByRole('navigation', { name: 'SDTM navigation' })
    expect(navigation.textContent).toContain('Current workbench')
    expect(navigation.textContent).toContain('Input selection')
    expect(navigation.textContent).toContain('Program & artifact readiness')
    const defineLink = screen.getByRole('link', { name: 'Define' })
    expect(defineLink.getAttribute('data-active')).toBe('true')
    expect(defineLink.getAttribute('href')).toBe('/sdtm/workbench-1?tab=define')
  })

  it('matches the EDC name-and-email account display without exposing the opaque username', async () => {
    const user = userEvent.setup()
    render(<SidebarProvider><AppSidebar /></SidebarProvider>)

    expect(screen.queryByText('24890137')).toBeNull()
    expect(screen.getByText('EDC User')).toBeTruthy()
    expect(screen.getByText('reviewer@example.test')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Open user menu for EDC User' }))
    expect(screen.queryByText('24890137')).toBeNull()
    expect(screen.getAllByText('EDC User')).toHaveLength(2)
    expect(screen.getAllByText('reviewer@example.test')).toHaveLength(2)
    await user.click(await screen.findByRole('menuitem', { name: /Sign out/ }))

    expect(signOutSpy).toHaveBeenCalledOnce()
    expect(navigateSpy).toHaveBeenCalledWith({
      to: '/login',
      search: { redirect: undefined },
    })
  })
})
