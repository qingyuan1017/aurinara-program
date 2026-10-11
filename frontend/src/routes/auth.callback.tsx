import { useEffect, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import { AuthLayout } from '@/components/layout/auth-layout'
import { completeOidcLogin } from '@/lib/oidc'

export const Route = createFileRoute('/auth/callback')({
  component: OidcCallbackPage,
})

function OidcCallbackPage() {
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void completeOidcLogin(window.location.search)
      .then((returnTo) => window.location.replace(returnTo))
      .catch(() => setError('Single sign-on could not be completed. Please try again.'))
  }, [])

  return (
    <AuthLayout>
      <div className="flex min-h-32 items-center justify-center text-sm">
        {error ?? (
          <span className="flex items-center gap-2">
            <Loader2 className="size-4 animate-spin" /> Completing secure sign-in…
          </span>
        )}
      </div>
    </AuthLayout>
  )
}
