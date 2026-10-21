import { FlaskConical } from 'lucide-react'

export function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-primary text-primary-foreground relative flex min-h-svh flex-col items-center justify-center gap-6 overflow-hidden p-6 before:absolute before:-top-56 before:-right-48 before:size-[34rem] before:rounded-full before:border before:border-[#e8c477]/20 before:shadow-[0_0_0_80px_rgb(232_196_119_/_0.05),0_0_0_160px_rgb(232_196_119_/_0.025)] md:p-10">
      <div className="relative z-10 flex w-full max-w-md flex-col gap-6">
        <div className="flex items-center justify-center gap-3 self-center">
          <div className="bg-[#e8c477] text-[#0d2e38] flex size-9 items-center justify-center rounded-lg shadow-sm">
            <FlaskConical className="size-5" />
          </div>
          <div className="grid leading-tight">
            <span className="font-display text-xl font-medium">Aurinara</span>
            <span className="text-[10px] font-semibold tracking-[0.14em] text-[#e8c477] uppercase">Clinical Artifacts</span>
          </div>
        </div>
        <div className="text-foreground [&_[data-slot=card]]:bg-card [&_[data-slot=card]]:shadow-2xl">{children}</div>
      </div>
    </div>
  )
}
