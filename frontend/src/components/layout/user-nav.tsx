import { Link, useNavigate } from '@tanstack/react-router'
import { ChevronDown, LogIn, LogOut } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAuth } from '@/components/auth-provider'

function initials(value: string): string {
  const name = value.split('@')[0] ?? value
  return name.slice(0, 2).toUpperCase() || 'AU'
}

export function UserNav() {
  const navigate = useNavigate()
  const { user, isAuthenticated, signOut } = useAuth()

  const label = user?.email ?? user?.username ?? null
  const displayName = user?.username ?? user?.email?.split('@')[0] ?? 'Account'

  function onSignOut() {
    signOut()
    navigate({ to: '/login', search: { redirect: undefined } })
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label="Open account menu"
        className="inline-flex h-10 max-w-56 items-center gap-2 rounded-md px-2 text-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary" aria-hidden="true">{isAuthenticated && label ? initials(label) : '?'}</span>
          <span className="hidden min-w-0 flex-1 text-left leading-tight lg:block">
            <span className="block truncate text-sm font-medium">{isAuthenticated ? displayName : 'Sign in'}</span>
            <span className="text-muted-foreground block truncate text-[11px] font-normal">{isAuthenticated ? (user?.email ?? 'Account') : 'Not signed in'}</span>
          </span>
          <ChevronDown className="text-muted-foreground hidden size-3.5 lg:block" aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-60" align="end" sideOffset={8}>
        <DropdownMenuLabel className="font-normal">
          <div>
            <p className="truncate text-sm font-medium">{isAuthenticated ? displayName : 'Not signed in'}</p>
            <p className="text-muted-foreground truncate text-xs">{isAuthenticated ? (label ?? 'Signed in') : 'Sign in to continue'}</p>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {isAuthenticated ? (
          <DropdownMenuItem className="text-destructive focus:bg-destructive/10 focus:text-destructive" onClick={onSignOut}>
            <LogOut className="mr-2 size-4" />
            Sign out
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem asChild>
            <Link to="/login" search={{ redirect: undefined }}>
              <LogIn className="mr-2 size-4" />
              Sign in
            </Link>
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
