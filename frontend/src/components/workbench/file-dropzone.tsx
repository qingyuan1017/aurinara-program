import * as React from 'react'
import { Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export interface FileDropzoneProps {
  /**
   * Called with the files the user selected, whether they were dropped onto the
   * target or chosen through the click-to-browse input. The same callback is the
   * single funnel for both paths, so a dropped file and a browsed file produce an
   * identical downstream request.
   */
  onFiles: (files: File[]) => void
  /** `accept` attribute forwarded to the native input (e.g. `.xpt`, `application/pdf`). */
  accept?: string
  /** Allow selecting more than one file. Defaults to single-file selection. */
  multiple?: boolean
  /** Disable both the drop target and the browse button. */
  disabled?: boolean
  /** Visible instruction text. */
  label?: React.ReactNode
  /** Secondary helper text (e.g. accepted types / size limits). */
  description?: React.ReactNode
  /** Accessible label for the drop region and browse control. */
  ariaLabel?: string
  className?: string
}

/**
 * Reusable file drop target that wraps a click-to-browse `<input type="file">`.
 *
 * Uses native HTML5 drag-and-drop (`dragover`/`drop`) for the drop affordance and
 * a visible button that triggers the hidden file input for the non-pointer path.
 * Both paths call {@link FileDropzoneProps.onFiles} with the selected `File[]`, so
 * the drop and browse routes are interchangeable and never diverge.
 */
export function FileDropzone({
  onFiles,
  accept,
  multiple = false,
  disabled = false,
  label = 'Drag a file here, or browse',
  description,
  ariaLabel = 'File upload drop target',
  className,
}: FileDropzoneProps) {
  const inputRef = React.useRef<HTMLInputElement>(null)
  const [isDragging, setIsDragging] = React.useState(false)

  const emit = React.useCallback(
    (fileList: FileList | null) => {
      if (!fileList || fileList.length === 0) return
      const files = Array.from(fileList)
      onFiles(multiple ? files : files.slice(0, 1))
    },
    [multiple, onFiles],
  )

  function openBrowser() {
    if (disabled) return
    inputRef.current?.click()
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (disabled) return
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      openBrowser()
    }
  }

  function handleDragOver(event: React.DragEvent<HTMLDivElement>) {
    if (disabled) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
    if (!isDragging) setIsDragging(true)
  }

  function handleDragLeave(event: React.DragEvent<HTMLDivElement>) {
    if (disabled) return
    // Only clear when leaving the dropzone itself, not a child.
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return
    setIsDragging(false)
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>) {
    if (disabled) return
    event.preventDefault()
    setIsDragging(false)
    emit(event.dataTransfer.files)
  }

  function handleInputChange(event: React.ChangeEvent<HTMLInputElement>) {
    emit(event.target.files)
    // Reset so selecting the same file again re-fires onChange.
    event.target.value = ''
  }

  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-label={ariaLabel}
      aria-disabled={disabled || undefined}
      data-dragging={isDragging || undefined}
      onKeyDown={handleKeyDown}
      onClick={openBrowser}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-md border border-dashed px-4 py-8 text-center text-sm transition-colors outline-none',
        'border-input hover:bg-accent/40 focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]',
        isDragging && 'border-ring bg-accent/60',
        disabled && 'pointer-events-none opacity-50',
        className,
      )}
    >
      <Upload className="text-muted-foreground size-6" aria-hidden="true" />
      <div className="font-medium">{label}</div>
      {description && (
        <div className="text-muted-foreground text-xs">{description}</div>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        onClick={(event) => {
          // Prevent the wrapper onClick from double-triggering the input.
          event.stopPropagation()
          openBrowser()
        }}
      >
        Browse files
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        onChange={handleInputChange}
        className="hidden"
        data-testid="file-dropzone-input"
      />
    </div>
  )
}
