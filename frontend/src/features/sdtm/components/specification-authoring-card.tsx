import * as React from 'react'
import { Pencil, Plus, Save, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ConfirmDialog } from '@/components/forms/confirm-dialog'
import { EmptyState } from '@/components/data/states'
import { SortableList } from '@/components/workbench/sortable-list'
import type { SdtmDomain, SdtmVariable } from '@/api/generated/model'

export interface SpecificationAuthoringCardProps {
  domains: SdtmDomain[]
  onChange: (next: SdtmDomain[]) => void
  onSave: () => void
  isSaving: boolean
}

interface DomainEditorState {
  index: number | null
  domain: SdtmDomain | null
}

interface VariableEditorState {
  domainIndex: number
  variableIndex: number | null
  variable: SdtmVariable | null
}

type DeleteTarget =
  | { kind: 'domain'; domainIndex: number }
  | { kind: 'variable'; domainIndex: number; variableIndex: number }

/**
 * Maintain the complete SDTM Specification draft. Domain and variable changes
 * remain local until the caller atomically saves the full Specification.
 */
export function SpecificationAuthoringCard({
  domains,
  onChange,
  onSave,
  isSaving,
}: SpecificationAuthoringCardProps) {
  const [domainEditor, setDomainEditor] =
    React.useState<DomainEditorState | null>(null)
  const [variableEditor, setVariableEditor] =
    React.useState<VariableEditorState | null>(null)
  const [deleteTarget, setDeleteTarget] = React.useState<DeleteTarget | null>(
    null,
  )
  const validationIssues = specificationDraftIssues(domains)

  function reorderVariables(
    domainIndex: number,
    nextVariables: SdtmDomain['variables'],
  ) {
    onChange(
      domains.map((domain, index) =>
        index === domainIndex ? { ...domain, variables: nextVariables } : domain,
      ),
    )
  }

  function saveDomain(nextDomain: SdtmDomain) {
    if (domainEditor?.index == null) {
      onChange([...domains, nextDomain])
    } else {
      onChange(
        domains.map((domain, index) =>
          index === domainEditor.index ? nextDomain : domain,
        ),
      )
    }
    setDomainEditor(null)
  }

  function saveVariable(nextVariable: SdtmVariable) {
    if (!variableEditor) return
    const { domainIndex, variableIndex } = variableEditor
    const domain = domains[domainIndex]
    if (!domain) return

    let nextDomain: SdtmDomain
    if (variableIndex == null) {
      nextDomain = {
        ...domain,
        variables: [...domain.variables, nextVariable],
      }
    } else {
      const previous = domain.variables[variableIndex]
      if (!previous) return
      nextDomain = {
        ...domain,
        variables: domain.variables.map((variable, index) =>
          index === variableIndex ? nextVariable : variable,
        ),
        keys: renameReference(domain.keys, previous.name, nextVariable.name),
        sort_order: renameReference(
          domain.sort_order,
          previous.name,
          nextVariable.name,
        ),
        value_level_metadata: domain.value_level_metadata?.map((item) =>
          item.variable === previous.name
            ? { ...item, variable: nextVariable.name }
            : item,
        ),
      }
    }
    onChange(
      domains.map((item, index) => (index === domainIndex ? nextDomain : item)),
    )
    setVariableEditor(null)
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    if (deleteTarget.kind === 'domain') {
      onChange(
        domains.filter((_, index) => index !== deleteTarget.domainIndex),
      )
      return
    }

    const domain = domains[deleteTarget.domainIndex]
    const variable = domain?.variables[deleteTarget.variableIndex]
    if (!domain || !variable) return
    const variables = domain.variables.filter(
      (_, index) => index !== deleteTarget.variableIndex,
    )
    const nextDomain: SdtmDomain = {
      ...domain,
      variables,
      keys: domain.keys.filter((name) => name !== variable.name),
      sort_order: domain.sort_order.filter((name) => name !== variable.name),
      value_level_metadata: domain.value_level_metadata?.filter(
        (item) => item.variable !== variable.name,
      ),
    }
    onChange(
      domains.map((item, index) =>
        index === deleteTarget.domainIndex ? nextDomain : item,
      ),
    )
  }

  const deleteDescription = deleteTarget
    ? deleteTarget.kind === 'domain'
      ? `Delete domain ${domains[deleteTarget.domainIndex]?.code ?? ''} and all of its variables from this draft?`
      : variableDeleteDescription(domains, deleteTarget)
    : undefined

  return (
    <Card>
      <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1.5">
          <CardTitle className="text-base">Domains and variables</CardTitle>
          <CardDescription>
            Create, edit, delete, and order target metadata. Changes are staged
            until you save the complete Specification.
          </CardDescription>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setDomainEditor({ index: null, domain: null })}
        >
          <Plus /> New domain
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {domains.length === 0 ? (
          <EmptyState
            title="No domains"
            description="Create a domain, add its variables, and complete its keys before saving."
          />
        ) : (
          domains.map((domain, domainIndex) => (
            <div
              key={`${domain.code}-${domainIndex}`}
              className="flex flex-col gap-3 rounded-md border p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-baseline gap-2 text-sm font-medium">
                    <code className="font-semibold">{domain.code}</code>
                    <span className="text-muted-foreground">{domain.label}</span>
                  </div>
                  <p className="text-muted-foreground mt-1 text-xs">
                    {domain.domain_class || 'No class'} ·{' '}
                    {domain.structure || 'No structure'} ·{' '}
                    {domain.expected_output_name || 'No output filename'}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    aria-label={`Add variable to ${domain.code}`}
                    onClick={() =>
                      setVariableEditor({
                        domainIndex,
                        variableIndex: null,
                        variable: null,
                      })
                    }
                  >
                    <Plus /> Add variable
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={`Edit domain ${domain.code}`}
                    onClick={() =>
                      setDomainEditor({ index: domainIndex, domain })
                    }
                  >
                    <Pencil />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={`Delete domain ${domain.code}`}
                    onClick={() =>
                      setDeleteTarget({ kind: 'domain', domainIndex })
                    }
                  >
                    <Trash2 />
                  </Button>
                </div>
              </div>

              {domain.variables.length === 0 ? (
                <EmptyState
                  title={`No variables in ${domain.code}`}
                  description="Add at least one variable before saving the Specification."
                />
              ) : (
                <SortableList
                  items={domain.variables}
                  getId={(variable) => variable.name}
                  ariaLabel={`${domain.code} variables`}
                  onReorder={(nextVariables) =>
                    reorderVariables(domainIndex, nextVariables)
                  }
                  renderItem={(variable, variableIndex) => (
                    <div className="flex min-w-0 items-center justify-between gap-3">
                      <div className="flex min-w-0 items-baseline gap-2 text-sm">
                        <code className="font-semibold">{variable.name}</code>
                        <span className="text-muted-foreground truncate">
                          {variable.label}
                        </span>
                        <span className="text-muted-foreground text-xs">
                          {variable.data_type} · {variable.core}
                        </span>
                      </div>
                      <div className="flex shrink-0 gap-1">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={`Edit ${domain.code}.${variable.name}`}
                          onClick={() =>
                            setVariableEditor({
                              domainIndex,
                              variableIndex,
                              variable,
                            })
                          }
                        >
                          <Pencil />
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={`Delete ${domain.code}.${variable.name}`}
                          onClick={() =>
                            setDeleteTarget({
                              kind: 'variable',
                              domainIndex,
                              variableIndex,
                            })
                          }
                        >
                          <Trash2 />
                        </Button>
                      </div>
                    </div>
                  )}
                />
              )}
            </div>
          ))
        )}

        {validationIssues.length > 0 && (
          <div
            className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm"
            role="alert"
          >
            <p className="font-medium">Complete the Specification before saving:</p>
            <ul className="mt-1 list-disc pl-5">
              {validationIssues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          </div>
        )}

        <div>
          <Button
            type="button"
            onClick={onSave}
            disabled={isSaving || validationIssues.length > 0}
          >
            <Save /> {isSaving ? 'Saving…' : 'Save Specification'}
          </Button>
        </div>
      </CardContent>

      <DomainDialog
        state={domainEditor}
        domains={domains}
        onOpenChange={(open) => {
          if (!open) setDomainEditor(null)
        }}
        onSave={saveDomain}
      />
      <VariableDialog
        state={variableEditor}
        domains={domains}
        onOpenChange={(open) => {
          if (!open) setVariableEditor(null)
        }}
        onSave={saveVariable}
      />
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
        title={deleteTarget?.kind === 'domain' ? 'Delete domain' : 'Delete variable'}
        description={deleteDescription}
        confirmLabel={deleteTarget?.kind === 'domain' ? 'Delete domain' : 'Delete variable'}
        onConfirm={confirmDelete}
        isPending={false}
        error={null}
        destructive
      />
    </Card>
  )
}

interface DomainFormState {
  code: string
  label: string
  domainClass: string
  structure: string
  keys: string
  sortOrder: string
  expectedOutputName: string
}

function DomainDialog({
  state,
  domains,
  onOpenChange,
  onSave,
}: {
  state: DomainEditorState | null
  domains: SdtmDomain[]
  onOpenChange: (open: boolean) => void
  onSave: (domain: SdtmDomain) => void
}) {
  const [form, setForm] = React.useState<DomainFormState>(emptyDomainForm())
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!state) return
    setForm(state.domain ? domainToForm(state.domain) : emptyDomainForm())
    setError(null)
  }, [state])

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const code = form.code.trim().toUpperCase()
    const expectedOutputName = form.expectedOutputName.trim().toLowerCase()
    if (!/^[A-Z][A-Z0-9]{1,7}$/.test(code)) {
      setError('Domain code must be 2–8 uppercase letters or digits, starting with a letter.')
      return
    }
    if (!form.label.trim() || form.label.trim().length > 40) {
      setError('Domain label is required and must be 40 characters or fewer.')
      return
    }
    if (!/^[a-z][a-z0-9_]{0,7}\.xpt$/.test(expectedOutputName)) {
      setError('Output filename must be a lowercase XPT name such as dm.xpt.')
      return
    }
    const duplicate = domains.some(
      (domain, index) => index !== state?.index && domain.code === code,
    )
    if (duplicate) {
      setError(`Domain ${code} already exists in this Specification.`)
      return
    }
    const duplicateOutput = domains.some(
      (domain, index) =>
        index !== state?.index &&
        domain.expected_output_name.toLowerCase() === expectedOutputName,
    )
    if (duplicateOutput) {
      setError(`Output filename ${expectedOutputName} is already in use.`)
      return
    }

    onSave({
      code,
      label: form.label.trim(),
      domain_class: form.domainClass.trim(),
      structure: form.structure.trim(),
      keys: splitNames(form.keys),
      sort_order: splitNames(form.sortOrder),
      expected_output_name: expectedOutputName,
      variables: state?.domain?.variables ?? [],
      value_level_metadata: state?.domain?.value_level_metadata ?? [],
    })
  }

  return (
    <Dialog open={state !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{state?.domain ? 'Edit domain' : 'New domain'}</DialogTitle>
          <DialogDescription>
            Maintain domain metadata. Keys and sort order are comma-separated
            variable names and must resolve before the Specification can be saved.
          </DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={submit}>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormItem>
              <FormLabel htmlFor="sdtm-domain-code">Domain code</FormLabel>
              <Input
                id="sdtm-domain-code"
                value={form.code}
                maxLength={8}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    code: event.target.value.toUpperCase(),
                  }))
                }
              />
            </FormItem>
            <FormItem>
              <FormLabel htmlFor="sdtm-domain-output">Output filename</FormLabel>
              <Input
                id="sdtm-domain-output"
                value={form.expectedOutputName}
                placeholder="dm.xpt"
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    expectedOutputName: event.target.value.toLowerCase(),
                  }))
                }
              />
            </FormItem>
          </div>
          <FormItem>
            <FormLabel htmlFor="sdtm-domain-label">Label</FormLabel>
            <Input
              id="sdtm-domain-label"
              value={form.label}
              maxLength={40}
              onChange={(event) =>
                setForm((current) => ({ ...current, label: event.target.value }))
              }
            />
          </FormItem>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormItem>
              <FormLabel htmlFor="sdtm-domain-class">Domain class</FormLabel>
              <Input
                id="sdtm-domain-class"
                value={form.domainClass}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    domainClass: event.target.value,
                  }))
                }
              />
            </FormItem>
            <FormItem>
              <FormLabel htmlFor="sdtm-domain-structure">Structure</FormLabel>
              <Input
                id="sdtm-domain-structure"
                value={form.structure}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    structure: event.target.value,
                  }))
                }
              />
            </FormItem>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormItem>
              <FormLabel htmlFor="sdtm-domain-keys">Keys</FormLabel>
              <Input
                id="sdtm-domain-keys"
                value={form.keys}
                placeholder="STUDYID, USUBJID"
                onChange={(event) =>
                  setForm((current) => ({ ...current, keys: event.target.value }))
                }
              />
            </FormItem>
            <FormItem>
              <FormLabel htmlFor="sdtm-domain-sort-order">Sort order</FormLabel>
              <Input
                id="sdtm-domain-sort-order"
                value={form.sortOrder}
                placeholder="USUBJID"
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    sortOrder: event.target.value,
                  }))
                }
              />
            </FormItem>
          </div>
          <FormMessage role="alert">{error}</FormMessage>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit">{state?.domain ? 'Save domain' : 'Create domain'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

interface VariableFormState {
  name: string
  label: string
  dataType: 'character' | 'numeric'
  length: string
  role: string
  core: 'Req' | 'Exp' | 'Perm'
  origin: string
  derived: boolean
  terminologyReleaseId: string
  codelistCode: string
  termCode: string
  extensionRevisionId: string
}

function VariableDialog({
  state,
  domains,
  onOpenChange,
  onSave,
}: {
  state: VariableEditorState | null
  domains: SdtmDomain[]
  onOpenChange: (open: boolean) => void
  onSave: (variable: SdtmVariable) => void
}) {
  const [form, setForm] = React.useState<VariableFormState>(emptyVariableForm())
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!state) return
    setForm(state.variable ? variableToForm(state.variable) : emptyVariableForm())
    setError(null)
  }, [state])

  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!state) return
    const name = form.name.trim().toUpperCase()
    if (!/^[A-Z][A-Z0-9_]{0,7}$/.test(name)) {
      setError('Variable name must be 1–8 uppercase letters, digits, or underscores.')
      return
    }
    if (!form.label.trim() || form.label.trim().length > 40) {
      setError('Variable label is required and must be 40 characters or fewer.')
      return
    }
    const duplicate = domains[state.domainIndex]?.variables.some(
      (variable, index) =>
        index !== state.variableIndex && variable.name === name,
    )
    if (duplicate) {
      setError(`Variable ${name} already exists in this domain.`)
      return
    }
    const length = form.length.trim() ? Number(form.length) : undefined
    if (
      length !== undefined &&
      (!Number.isInteger(length) || length < 1 || length > 200)
    ) {
      setError('Length must be a whole number from 1 through 200.')
      return
    }
    const hasTerminology = [
      form.terminologyReleaseId,
      form.codelistCode,
      form.termCode,
      form.extensionRevisionId,
    ].some((value) => value.trim())
    if (
      hasTerminology &&
      (!form.terminologyReleaseId.trim() || !form.codelistCode.trim())
    ) {
      setError('A terminology binding requires both a release ID and codelist code.')
      return
    }

    onSave({
      name,
      label: form.label.trim(),
      data_type: form.dataType,
      length,
      role: form.role.trim(),
      core: form.core,
      origin: form.origin.trim(),
      derived: form.derived,
      terminology_binding: hasTerminology
        ? {
            terminology_release_id: form.terminologyReleaseId.trim(),
            codelist_code: form.codelistCode.trim(),
            term_code: form.termCode.trim() || undefined,
            extension_revision_id: form.extensionRevisionId.trim() || undefined,
          }
        : undefined,
    })
  }

  const domainCode = state ? domains[state.domainIndex]?.code : undefined
  return (
    <Dialog open={state !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{state?.variable ? 'Edit variable' : 'New variable'}</DialogTitle>
          <DialogDescription>
            Maintain a variable in domain {domainCode ?? ''}. Renaming a variable
            also updates its domain key, sort-order, and value-level references.
          </DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={submit}>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormItem>
              <FormLabel htmlFor="sdtm-variable-name">Variable name</FormLabel>
              <Input
                id="sdtm-variable-name"
                value={form.name}
                maxLength={8}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    name: event.target.value.toUpperCase(),
                  }))
                }
              />
            </FormItem>
            <FormItem>
              <FormLabel htmlFor="sdtm-variable-label">Label</FormLabel>
              <Input
                id="sdtm-variable-label"
                value={form.label}
                maxLength={40}
                onChange={(event) =>
                  setForm((current) => ({ ...current, label: event.target.value }))
                }
              />
            </FormItem>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <FormItem>
              <FormLabel htmlFor="sdtm-variable-data-type">Data type</FormLabel>
              <Select
                value={form.dataType}
                onValueChange={(value: 'character' | 'numeric') =>
                  setForm((current) => ({ ...current, dataType: value }))
                }
              >
                <SelectTrigger id="sdtm-variable-data-type" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="character">Character</SelectItem>
                  <SelectItem value="numeric">Numeric</SelectItem>
                </SelectContent>
              </Select>
            </FormItem>
            <FormItem>
              <FormLabel htmlFor="sdtm-variable-length">Length</FormLabel>
              <Input
                id="sdtm-variable-length"
                type="number"
                min={1}
                max={200}
                value={form.length}
                onChange={(event) =>
                  setForm((current) => ({ ...current, length: event.target.value }))
                }
              />
            </FormItem>
            <FormItem>
              <FormLabel htmlFor="sdtm-variable-core">Core</FormLabel>
              <Select
                value={form.core}
                onValueChange={(value: 'Req' | 'Exp' | 'Perm') =>
                  setForm((current) => ({ ...current, core: value }))
                }
              >
                <SelectTrigger id="sdtm-variable-core" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="Req">Required</SelectItem>
                  <SelectItem value="Exp">Expected</SelectItem>
                  <SelectItem value="Perm">Permissible</SelectItem>
                </SelectContent>
              </Select>
            </FormItem>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormItem>
              <FormLabel htmlFor="sdtm-variable-role">Role</FormLabel>
              <Input
                id="sdtm-variable-role"
                value={form.role}
                onChange={(event) =>
                  setForm((current) => ({ ...current, role: event.target.value }))
                }
              />
            </FormItem>
            <FormItem>
              <FormLabel htmlFor="sdtm-variable-origin">Origin</FormLabel>
              <Input
                id="sdtm-variable-origin"
                value={form.origin}
                onChange={(event) =>
                  setForm((current) => ({ ...current, origin: event.target.value }))
                }
              />
            </FormItem>
          </div>
          <label className="flex items-center gap-2 text-sm font-medium">
            <input
              type="checkbox"
              checked={form.derived}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  derived: event.target.checked,
                }))
              }
            />
            Derived variable
          </label>
          <fieldset className="grid gap-4 rounded-md border p-3">
            <legend className="px-1 text-sm font-medium">
              Terminology binding (optional)
            </legend>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormItem>
                <FormLabel htmlFor="sdtm-variable-terminology-release">
                  Terminology release ID
                </FormLabel>
                <Input
                  id="sdtm-variable-terminology-release"
                  value={form.terminologyReleaseId}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      terminologyReleaseId: event.target.value,
                    }))
                  }
                />
              </FormItem>
              <FormItem>
                <FormLabel htmlFor="sdtm-variable-codelist">Codelist code</FormLabel>
                <Input
                  id="sdtm-variable-codelist"
                  value={form.codelistCode}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      codelistCode: event.target.value,
                    }))
                  }
                />
              </FormItem>
              <FormItem>
                <FormLabel htmlFor="sdtm-variable-term">Term code</FormLabel>
                <Input
                  id="sdtm-variable-term"
                  value={form.termCode}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, termCode: event.target.value }))
                  }
                />
              </FormItem>
              <FormItem>
                <FormLabel htmlFor="sdtm-variable-extension">
                  Extension revision ID
                </FormLabel>
                <Input
                  id="sdtm-variable-extension"
                  value={form.extensionRevisionId}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      extensionRevisionId: event.target.value,
                    }))
                  }
                />
              </FormItem>
            </div>
          </fieldset>
          <FormMessage role="alert">{error}</FormMessage>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit">
              {state?.variable ? 'Save variable' : 'Create variable'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function emptyDomainForm(): DomainFormState {
  return {
    code: '',
    label: '',
    domainClass: '',
    structure: '',
    keys: '',
    sortOrder: '',
    expectedOutputName: '',
  }
}

function domainToForm(domain: SdtmDomain): DomainFormState {
  return {
    code: domain.code,
    label: domain.label,
    domainClass: domain.domain_class,
    structure: domain.structure,
    keys: domain.keys.join(', '),
    sortOrder: domain.sort_order.join(', '),
    expectedOutputName: domain.expected_output_name,
  }
}

function emptyVariableForm(): VariableFormState {
  return {
    name: '',
    label: '',
    dataType: 'character',
    length: '',
    role: '',
    core: 'Req',
    origin: '',
    derived: false,
    terminologyReleaseId: '',
    codelistCode: '',
    termCode: '',
    extensionRevisionId: '',
  }
}

function variableToForm(variable: SdtmVariable): VariableFormState {
  return {
    name: variable.name,
    label: variable.label,
    dataType: variable.data_type === 'numeric' ? 'numeric' : 'character',
    length: variable.length == null ? '' : String(variable.length),
    role: variable.role,
    core: variable.core,
    origin: variable.origin,
    derived: variable.derived ?? false,
    terminologyReleaseId:
      variable.terminology_binding?.terminology_release_id ?? '',
    codelistCode: variable.terminology_binding?.codelist_code ?? '',
    termCode: variable.terminology_binding?.term_code ?? '',
    extensionRevisionId:
      variable.terminology_binding?.extension_revision_id ?? '',
  }
}

function splitNames(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean)
}

function renameReference(
  names: string[],
  previousName: string,
  nextName: string,
): string[] {
  return names.map((name) => (name === previousName ? nextName : name))
}

function variableDeleteDescription(
  domains: SdtmDomain[],
  target: Extract<DeleteTarget, { kind: 'variable' }>,
): string {
  const domain = domains[target.domainIndex]
  const variable = domain?.variables[target.variableIndex]
  const referenced =
    !!variable &&
    (domain.keys.includes(variable.name) ||
      domain.sort_order.includes(variable.name) ||
      !!domain.value_level_metadata?.some(
        (item) => item.variable === variable.name,
      ))
  return `Delete variable ${domain?.code ?? ''}.${variable?.name ?? ''} from this draft?${
    referenced
      ? ' Its key, sort-order, and value-level references will also be removed.'
      : ''
  }`
}

function specificationDraftIssues(domains: SdtmDomain[]): string[] {
  if (domains.length === 0) return ['At least one domain is required.']
  const issues: string[] = []
  const codes = new Set<string>()
  const outputs = new Set<string>()

  for (const domain of domains) {
    if (codes.has(domain.code)) issues.push(`Domain code ${domain.code} is duplicated.`)
    codes.add(domain.code)
    if (outputs.has(domain.expected_output_name)) {
      issues.push(`Output filename ${domain.expected_output_name} is duplicated.`)
    }
    outputs.add(domain.expected_output_name)

    const names = new Set(domain.variables.map((variable) => variable.name))
    if (domain.variables.length === 0) {
      issues.push(`${domain.code} requires at least one variable.`)
    }
    if (domain.keys.length === 0) issues.push(`${domain.code} requires at least one key.`)
    if (domain.sort_order.length === 0) {
      issues.push(`${domain.code} requires at least one sort-order variable.`)
    }
    for (const name of [...domain.keys, ...domain.sort_order]) {
      if (!names.has(name)) {
        issues.push(`${domain.code} references undeclared variable ${name}.`)
      }
    }
    for (const item of domain.value_level_metadata ?? []) {
      if (!names.has(item.variable)) {
        issues.push(
          `${domain.code} value-level metadata references undeclared variable ${item.variable}.`,
        )
      }
    }
  }
  return [...new Set(issues)]
}
