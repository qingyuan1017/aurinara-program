import { ArrowDown, ArrowUp, Copy, Plus, Trash2 } from 'lucide-react'

import type {
  CustomFunctionDefinition,
  CustomFunctionImplementation,
} from '@/api/generated/model'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { customFunctionIssues } from './custom-function-validation'

const RETURN_TYPES = ['character', 'numeric', 'logical', 'date', 'datetime'] as const
const LANGUAGES = ['python', 'r', 'sas'] as const

export interface CustomFunctionEditorProps {
  functions: CustomFunctionDefinition[]
  onChange: (next: CustomFunctionDefinition[]) => void
  onSignatureChange?: (
    previous: CustomFunctionDefinition,
    next: CustomFunctionDefinition,
  ) => void
  disabled?: boolean
}

/** Typed editor for plan-owned custom function signatures and language bodies. */
export function CustomFunctionEditor({
  functions,
  onChange,
  onSignatureChange,
  disabled = false,
}: CustomFunctionEditorProps) {
  function update(index: number, next: CustomFunctionDefinition) {
    onSignatureChange?.(functions[index], next)
    onChange(functions.map((item, itemIndex) => (itemIndex === index ? next : item)))
  }

  function add() {
    let id = 'new_function'
    let suffix = 2
    while (functions.some((item) => item.id === id)) {
      id = `new_function_${suffix}`
      suffix += 1
    }
    onChange([
      ...functions,
      {
        id,
        parameters: ['value'],
        return_type: 'character',
        implementations: [{ language: 'python', source: '' }],
      },
    ])
  }

  function duplicate(index: number) {
    const source = functions[index]
    let id = `${source.id}_copy`
    let suffix = 2
    while (functions.some((item) => item.id === id)) {
      id = `${source.id}_copy_${suffix}`
      suffix += 1
    }
    const copy = JSON.parse(JSON.stringify(source)) as CustomFunctionDefinition
    copy.id = id
    onChange([...functions.slice(0, index + 1), copy, ...functions.slice(index + 1)])
  }

  return (
    <div className="flex flex-col gap-3">
      {functions.length === 0 && (
        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
          No custom functions. Add one only when the built-in typed functions cannot
          express the required derivation.
        </p>
      )}
      {functions.map((definition, index) => (
        <FunctionCard
          key={index}
          definition={definition}
          allFunctions={functions}
          index={index}
          disabled={disabled}
          onChange={(next) => update(index, next)}
          onRename={(nextId) => update(index, { ...definition, id: nextId })}
          onDuplicate={() => duplicate(index)}
          onRemove={() => onChange(functions.filter((_, itemIndex) => itemIndex !== index))}
        />
      ))}
      <Button type="button" variant="outline" size="sm" className="w-fit" onClick={add} disabled={disabled}>
        <Plus /> Add custom function
      </Button>
    </div>
  )
}

function FunctionCard({
  definition,
  allFunctions,
  index,
  disabled,
  onChange,
  onRename,
  onDuplicate,
  onRemove,
}: {
  definition: CustomFunctionDefinition
  allFunctions: readonly CustomFunctionDefinition[]
  index: number
  disabled: boolean
  onChange: (next: CustomFunctionDefinition) => void
  onRename: (next: string) => void
  onDuplicate: () => void
  onRemove: () => void
}) {
  const issues = customFunctionIssues(definition, allFunctions, index)

  function setParameter(parameterIndex: number, next: string) {
    onChange({
      ...definition,
      parameters: definition.parameters.map((item, itemIndex) =>
        itemIndex === parameterIndex ? next : item,
      ),
    })
  }

  function moveParameter(parameterIndex: number, offset: -1 | 1) {
    const destination = parameterIndex + offset
    if (destination < 0 || destination >= definition.parameters.length) return
    const parameters = [...definition.parameters]
    ;[parameters[parameterIndex], parameters[destination]] = [
      parameters[destination],
      parameters[parameterIndex],
    ]
    onChange({ ...definition, parameters })
  }

  function addImplementation() {
    const language = LANGUAGES.find(
      (candidate) => !definition.implementations.some((item) => item.language === candidate),
    )
    if (!language) return
    onChange({
      ...definition,
      implementations: [...definition.implementations, { language, source: '' }],
    })
  }

  function updateImplementation(
    implementationIndex: number,
    next: CustomFunctionImplementation,
  ) {
    onChange({
      ...definition,
      implementations: definition.implementations.map((item, itemIndex) =>
        itemIndex === implementationIndex ? next : item,
      ),
    })
  }

  return (
    <section className="flex flex-col gap-3 rounded-md border p-3" data-slot="custom-function-card">
      <div className="flex items-end gap-2">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <Label className="text-xs text-muted-foreground">Function ID</Label>
          <Input
            value={definition.id}
            onChange={(event) => onRename(event.target.value)}
            disabled={disabled}
            className="font-mono"
            aria-label={`Custom function ${index + 1} ID`}
          />
        </div>
        <div className="flex w-40 flex-col gap-1">
          <Label className="text-xs text-muted-foreground">Returns</Label>
          <Select
            value={definition.return_type}
            onValueChange={(returnType) =>
              onChange({
                ...definition,
                return_type: returnType as CustomFunctionDefinition['return_type'],
              })
            }
            disabled={disabled}
          >
            <SelectTrigger aria-label={`Custom function ${definition.id} return type`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RETURN_TYPES.map((returnType) => (
                <SelectItem key={returnType} value={returnType}>{returnType}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button type="button" variant="ghost" size="icon" onClick={onDuplicate} disabled={disabled} aria-label={`Duplicate custom function ${definition.id}`}>
          <Copy />
        </Button>
        <Button type="button" variant="ghost" size="icon" onClick={onRemove} disabled={disabled} aria-label={`Remove custom function ${definition.id}`}>
          <Trash2 />
        </Button>
      </div>

      <div className="flex flex-wrap gap-1">
        <Badge variant={issues.length === 0 ? 'secondary' : 'destructive'}>
          {issues.length === 0 ? 'Ready' : 'Needs attention'}
        </Badge>
        {issues.map((issue) => <Badge key={issue} variant="outline">{issue}</Badge>)}
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <Label>Parameters</Label>
          <span className="text-xs text-muted-foreground">Names appear in every call recipe</span>
        </div>
        {definition.parameters.map((parameter, parameterIndex) => (
          <div key={parameterIndex} className="flex items-center gap-1">
            <span className="w-6 text-right text-xs text-muted-foreground">{parameterIndex + 1}</span>
            <Input
              value={parameter}
              onChange={(event) => setParameter(parameterIndex, event.target.value)}
              disabled={disabled}
              className="font-mono"
              aria-label={`Parameter ${parameterIndex + 1} for ${definition.id}`}
            />
            <Button type="button" variant="ghost" size="icon" onClick={() => moveParameter(parameterIndex, -1)} disabled={disabled || parameterIndex === 0} aria-label={`Move parameter ${parameterIndex + 1} up`}><ArrowUp /></Button>
            <Button type="button" variant="ghost" size="icon" onClick={() => moveParameter(parameterIndex, 1)} disabled={disabled || parameterIndex === definition.parameters.length - 1} aria-label={`Move parameter ${parameterIndex + 1} down`}><ArrowDown /></Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => onChange({ ...definition, parameters: definition.parameters.filter((_, itemIndex) => itemIndex !== parameterIndex) })}
              disabled={disabled}
              aria-label={`Remove parameter ${parameterIndex + 1}`}
            ><Trash2 /></Button>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-fit"
          onClick={() => onChange({ ...definition, parameters: [...definition.parameters, `parameter_${definition.parameters.length + 1}`] })}
          disabled={disabled || definition.parameters.length >= 32}
        ><Plus /> Add parameter</Button>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <Label>Language bodies</Label>
          <span className="text-xs text-muted-foreground">Run only in isolated runners</span>
        </div>
        {definition.implementations.map((implementation, implementationIndex) => (
          <div key={implementation.language} className="flex flex-col gap-1 rounded-md border p-2">
            <div className="flex items-center justify-between">
              <Badge variant="outline">{implementation.language}</Badge>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => onChange({ ...definition, implementations: definition.implementations.filter((_, itemIndex) => itemIndex !== implementationIndex) })}
                disabled={disabled || definition.implementations.length === 1}
                aria-label={`Remove ${implementation.language} body from ${definition.id}`}
              ><Trash2 /> Remove</Button>
            </div>
            <Textarea
              value={implementation.source}
              onChange={(event) => updateImplementation(implementationIndex, { ...implementation, source: event.target.value })}
              disabled={disabled}
              rows={7}
              spellCheck={false}
              className="font-mono text-xs"
              placeholder={`Enter the manually authored ${implementation.language} function body`}
              aria-label={`${implementation.language} body for ${definition.id}`}
            />
          </div>
        ))}
        <Button type="button" variant="outline" size="sm" className="w-fit" onClick={addImplementation} disabled={disabled || definition.implementations.length === LANGUAGES.length}>
          <Plus /> Add language body
        </Button>
      </div>
    </section>
  )
}

