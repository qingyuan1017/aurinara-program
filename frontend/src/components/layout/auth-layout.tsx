import { FlaskConical } from 'lucide-react'

export function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-muted/40 flex min-h-svh flex-col items-center justify-center gap-6 p-6 md:p-10">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <div className="flex items-center justify-center gap-2 self-center font-medium">
          <div className="bg-primary text-primary-foreground flex size-8 items-center justify-center rounded-lg">
            <FlaskConical className="size-5" />
          </div>
          <span className="text-lg font-semibold">Aurinara</span>
        </div>
        {children}
      </div>
    </div>
  )
}
