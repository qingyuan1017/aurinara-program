import { Check, Moon, Sun, SunMoon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useTheme } from '@/components/theme-provider'

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon">
          <SunMoon className="size-4" />
          <span className="sr-only">Theme: {theme}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => setTheme('light')} aria-current={theme === 'light' ? 'true' : undefined}>
          <Sun className="mr-2 size-4" />Light{theme === 'light' && <Check className="ml-auto size-4" />}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => setTheme('dark')} aria-current={theme === 'dark' ? 'true' : undefined}>
          <Moon className="mr-2 size-4" />Dark{theme === 'dark' && <Check className="ml-auto size-4" />}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => setTheme('system')} aria-current={theme === 'system' ? 'true' : undefined}>
          <SunMoon className="mr-2 size-4" />System{theme === 'system' && <Check className="ml-auto size-4" />}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
