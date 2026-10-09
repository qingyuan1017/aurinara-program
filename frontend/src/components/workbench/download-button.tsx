import { Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useDownload } from '@/hooks/use-download'

/**
 * Download an immutable artifact by id through the binary bypass
 * ({@link useDownload} -> `GET /api/v1/artifacts/{artifactId}/download`), which
 * inherits the base URL and bearer interceptor and saves via a transient
 * object-URL anchor (Requirement 8.4).
 *
 * This is a self-contained trigger: it owns its own {@link useDownload}
 * instance so a caller can drop one button per artifact row without threading
 * download state. When several buttons should share a single pending/error
 * state, pass a shared `download` handle instead.
 */
export interface DownloadButtonProps {
  /** The immutable artifact id to download. */
  artifactId: string
  /** Display filename used when the response carries no `Content-Disposition`. */
  filename?: string
  /** Optional label; defaults to "Download". */
  label?: string
  /** Button size, forwarded to the shared `Button`. */
  size?: 'default' | 'sm' | 'lg' | 'icon'
  /** Button variant, forwarded to the shared `Button`. Defaults to `outline`. */
  variant?: 'default' | 'secondary' | 'outline' | 'ghost' | 'link'
  disabled?: boolean
  className?: string
  /**
   * Optional shared download handle. When omitted, the button creates its own
   * {@link useDownload} instance. Supplying one lets a list share a single
   * pending/error state across rows.
   */
  download?: Pick<ReturnType<typeof useDownload>, 'downloadArtifact' | 'isPending'>
}

export function DownloadButton({
  artifactId,
  filename,
  label = 'Download',
  size = 'sm',
  variant = 'outline',
  disabled,
  className,
  download,
}: DownloadButtonProps) {
  const ownDownload = useDownload()
  const handle = download ?? ownDownload

  return (
    <Button
      type="button"
      size={size}
      variant={variant}
      className={className}
      disabled={disabled || handle.isPending}
      onClick={() => {
        // Fire-and-forget: `useDownload` records the error on its own state.
        void handle.downloadArtifact(artifactId, filename)
      }}
    >
      <Download aria-hidden />
      {label}
    </Button>
  )
}

export default DownloadButton
