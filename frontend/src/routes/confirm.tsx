import { useState } from 'react'
import {
  Link,
  createFileRoute,
  useNavigate,
  useSearch,
} from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AuthLayout } from '@/components/layout/auth-layout'
import { AuthError, confirmSignUp, resendConfirmationCode } from '@/lib/cognito'

export const Route = createFileRoute('/confirm')({
  validateSearch: (search: Record<string, unknown>) => ({
    username: typeof search.username === 'string' ? search.username : '',
  }),
  component: ConfirmPage,
})

function ConfirmPage() {
  const navigate = useNavigate()
  const { username } = useSearch({ from: '/confirm' })

  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setNotice(null)
    setSubmitting(true)
    try {
      await confirmSignUp(username, code)
      navigate({ to: '/login', search: { redirect: undefined } })
    } catch (err) {
      setError(
        err instanceof AuthError ? err.message : 'Confirmation failed.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  async function onResend() {
    setError(null)
    setNotice(null)
    try {
      await resendConfirmationCode(username)
      setNotice('A new code has been sent to your email.')
    } catch (err) {
      setError(err instanceof AuthError ? err.message : 'Could not resend code.')
    }
  }

  return (
    <AuthLayout>
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-xl">Confirm your account</CardTitle>
          <CardDescription>
            Enter the verification code sent to {username || 'your email'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="flex flex-col gap-5">
            <div className="grid gap-2">
              <Label htmlFor="code">Verification code</Label>
              <Input
                id="code"
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="123456"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
              />
            </div>

            {error && (
              <p className="text-destructive text-sm" role="alert">
                {error}
              </p>
            )}
            {notice && <p className="text-sm text-emerald-600">{notice}</p>}

            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting && <Loader2 className="size-4 animate-spin" />}
              Confirm account
            </Button>
          </form>

          <div className="text-muted-foreground mt-4 flex flex-col items-center gap-2 text-center text-sm">
            <button
              type="button"
              onClick={onResend}
              className="text-foreground underline underline-offset-4"
            >
              Resend code
            </button>
            <Link
              to="/login"
              search={{ redirect: undefined }}
              className="text-foreground underline underline-offset-4"
            >
              Back to sign in
            </Link>
          </div>
        </CardContent>
      </Card>
    </AuthLayout>
  )
}
