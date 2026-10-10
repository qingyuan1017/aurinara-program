import * as React from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { FileDropzone } from '@/components/workbench/file-dropzone'
import {
  parsePlanJsonImport,
  type ImportedPlanGraph,
} from './plan-json-import'

export interface PlanJsonImportDialogProps {
  /** The domain currently being edited; the imported plan's `domain` must match. */
  domainCode: string
  open: boolean
  onOpenChange: (open: boolean) => void
  /**
   * Called with the parsed, domain-matched node/edge arrays when the user
   * applies a valid import. The caller loads them onto the canvas; the existing
   * "Save plan" flow then persists them (pinning revisions, If-Match, and full
   * backend validation).
   */
  onImport: (graph: ImportedPlanGraph) => void
}

/**
 * Import a per-domain SDTM Derivation Plan from JSON instead of authoring it in
 * the drag-and-drop graph. The user pastes JSON or uploads a `.json` file; on
 * apply the text is parsed and validated for this domain (see
 * {@link parsePlanJsonImport}) and the resulting nodes/edges are handed to
 * `onImport`. The dialog never persists anything itself — it only populates the
 * canvas, so the existing Save flow stays the single authority for revision
 * pinning and backend validation. The pasted text is retained on a parse error
 * so the user can fix and retry.
 */
export function PlanJsonImportDialog({
  domainCode,
  open,
  onOpenChange,
  onImport,
}: PlanJsonImportDialogProps) {
  const [text, setText] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)

  // Reset the editor whenever the dialog is (re)opened.
  React.useEffect(() => {
    if (open) {
      setText('')
      setError(null)
    }
  }, [open])

  async function handleFile(files: File[]) {
    const file = files[0]
    if (!file) return
    setError(null)
    try {
      setText(await file.text())
    } catch {
      setError('Could not read that file. Paste the JSON instead.')
    }
  }

  function handleApply() {
    const result = parsePlanJsonImport(text, domainCode)
    if (!result.ok) {
      setError(result.error)
      return
    }
    onImport(result.value)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Import {domainCode} derivation plan JSON</DialogTitle>
          <DialogDescription>
            Paste or upload a derivation plan JSON for this domain. The nodes
            load onto the canvas; review them, then use Save plan to persist.
          </DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
          {error && (
            <div
              role="alert"
              className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm"
            >
              {error}
            </div>
          )}

          <FileDropzone
            accept=".json,application/json"
            onFiles={handleFile}
            ariaLabel="Derivation plan JSON upload drop target"
            label="Drag a .json plan file here, or browse"
            description="The file's domain must match this editor's domain."
          />

          <div className="flex flex-col gap-2">
            <Label htmlFor="plan-json-text">Plan JSON</Label>
            <Textarea
              id="plan-json-text"
              value={text}
              onChange={(event) => {
                setText(event.target.value)
                if (error) setError(null)
              }}
              rows={14}
              spellCheck={false}
              placeholder={`{\n  "domain": "${domainCode}",\n  "nodes": [ ... ],\n  "edges": [ ... ]\n}`}
              className="font-mono text-xs"
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button type="button" disabled={!text.trim()} onClick={handleApply}>
            Load onto canvas
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default PlanJsonImportDialog
