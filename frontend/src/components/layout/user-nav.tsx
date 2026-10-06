import { Link, useNavigate } from '@tanstack/react-router'
import { LogIn, LogOut } from 'lucide-react'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
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

  function onSignOut() {
    signOut()
    navigate({ to: '/login', search: { redirect: undefined } })
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="relative size-8 rounded-full">
          <Avatar className="size-8">
            <AvatarFallback>
              {isAuthenticated && label ? initials(label) : '?'}
            </AvatarFallback>
          </Avatar>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56" align="end" forceMount>
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-1">
            <p className="text-sm leading-none font-medium">
              {isAuthenticated ? 'Account' : 'Not signed in'}
            </p>
            <p className="text-muted-foreground text-xs leading-none">
              {isAuthenticated ? (label ?? 'Signed in') : 'Sign in to continue'}
            </p>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {isAuthenticated ? (
          <DropdownMenuItem variant="destructive" onClick={onSignOut}>
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
