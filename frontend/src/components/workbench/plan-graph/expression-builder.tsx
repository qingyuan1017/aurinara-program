import * as React from 'react'
import { Plus, Trash2 } from 'lucide-react'
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
import {
  BinaryExpressionOperator,
  UnaryExpressionOperator,
} from '@/api/generated/model'
import type {
  BinaryExpression,
  ColumnExpression,
  LiteralExpression,
  UnaryExpression,
} from '@/api/generated/model'

/**
 * A structured, strictly typed expression editor used by the `derive`, `filter`
 * and `assert` operator inspectors.
 *
 * It builds the generated `LiteralExpression | ColumnExpression |
 * UnaryExpression | BinaryExpression` union recursively and NEVER exposes a
 * free-text Python/R/SAS/SQL field — the operator and expression kinds are
 * chosen from fixed selects, and the only free text is a literal value or a
 * column/dataset identifier. This is the platform boundary that keeps raw code
 * strings out of the authoring model (AGENTS.md "Compilation and execution").
 */
export type PlanExpression =
  | LiteralExpression
  | ColumnExpression
  | UnaryExpression
  | BinaryExpression

type ExpressionKind = PlanExpression['kind']

const KIND_OPTIONS: { value: ExpressionKind; label: string }[] = [
  { value: 'column', label: 'Column' },
  { value: 'literal', label: 'Literal value' },
  { value: 'unary', label: 'Unary operation' },
  { value: 'binary', label: 'Binary operation' },
]

const BINARY_OPERATORS = Object.values(BinaryExpressionOperator)
const UNARY_OPERATORS = Object.values(UnaryExpressionOperator)

/** A fresh default expression for a newly selected kind. */
// eslint-disable-next-line react-refresh/only-export-components
export function defaultExpression(kind: ExpressionKind): PlanExpression {
  switch (kind) {
    case 'literal':
      return { kind: 'literal', value: '' }
    case 'column':
      return { kind: 'column', dataset: '', column: '' }
    case 'unary':
      return {
        kind: 'unary',
        operator: 'is_null',
        operand: { kind: 'column', dataset: '', column: '' },
      }
    case 'binary':
      return {
        kind: 'binary',
        operator: 'eq',
        left: { kind: 'column', dataset: '', column: '' },
        right: { kind: 'literal', value: '' },
      }
  }
}

export interface ExpressionBuilderProps {
  value: PlanExpression
  onChange: (next: PlanExpression) => void
  disabled?: boolean
  /** Nesting depth guard so deeply recursive expressions stay readable. */
  depth?: number
  /** Accessible label for the kind selector at this level. */
  label?: string
}

/**
 * Recursive typed-expression editor. Each level picks a `kind` from a fixed
 * select; the fields below adapt to the chosen kind. No level renders a
 * free-text code input.
 */
export function ExpressionBuilder({
  value,
  onChange,
  disabled = false,
  depth = 0,
  label = 'Expression',
}: ExpressionBuilderProps) {
  const kindId = React.useId()

  function changeKind(kind: ExpressionKind) {
    if (kind === value.kind) return
    onChange(defaultExpression(kind))
  }

  return (
    <div
      className="flex flex-col gap-2 rounded-md border border-dashed p-2"
      data-depth={depth}
    >
      <div className="flex flex-col gap-1">
        <Label htmlFor={kindId} className="text-xs text-muted-foreground">
          {label}
        </Label>
        <Select
          value={value.kind}
          onValueChange={(next) => changeKind(next as ExpressionKind)}
          disabled={disabled}
        >
          <SelectTrigger id={kindId} size="sm" aria-label={`${label} kind`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {KIND_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {value.kind === 'literal' && (
        <LiteralFields value={value} onChange={onChange} disabled={disabled} />
      )}
      {value.kind === 'column' && (
        <ColumnFields value={value} onChange={onChange} disabled={disabled} />
      )}
      {value.kind === 'unary' && (
        <UnaryFields
          value={value}
          onChange={onChange}
          disabled={disabled}
          depth={depth}
        />
      )}
      {value.kind === 'binary' && (
        <BinaryFields
          value={value}
          onChange={onChange}
          disabled={disabled}
          depth={depth}
        />
      )}
    </div>
  )
}

function LiteralFields({
  value,
  onChange,
  disabled,
}: {
  value: LiteralExpression
  onChange: (next: PlanExpression) => void
  disabled: boolean
}) {
  const valueId = React.useId()
  const typeId = React.useId()

  const literalType = literalTypeOf(value.value)

  function changeType(nextType: LiteralType) {
    onChange({ kind: 'literal', value: coerceLiteral(value.value, nextType) })
  }

  function changeRaw(raw: string) {
    onChange({ kind: 'literal', value: parseLiteral(raw, literalType) })
  }

  return (
    <div className="grid grid-cols-[8rem_1fr] gap-2">
      <div className="flex flex-col gap-1">
        <Label htmlFor={typeId} className="text-xs text-muted-foreground">
          Type
        </Label>
        <Select
          value={literalType}
          onValueChange={(next) => changeType(next as LiteralType)}
          disabled={disabled}
        >
          <SelectTrigger id={typeId} size="sm" aria-label="Literal type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="string">Text</SelectItem>
            <SelectItem value="number">Number</SelectItem>
            <SelectItem value="boolean">Boolean</SelectItem>
            <SelectItem value="null">Null</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={valueId} className="text-xs text-muted-foreground">
          Value
        </Label>
        {literalType === 'boolean' ? (
          <Select
            value={String(value.value === true)}
            onValueChange={(next) =>
              onChange({ kind: 'literal', value: next === 'true' })
            }
            disabled={disabled}
          >
            <SelectTrigger id={valueId} size="sm" aria-label="Boolean value">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="true">true</SelectItem>
              <SelectItem value="false">false</SelectItem>
            </SelectContent>
          </Select>
        ) : literalType === 'null' ? (
          <Input id={valueId} value="null" disabled readOnly aria-label="Null value" />
        ) : (
          <Input
            id={valueId}
            value={value.value == null ? '' : String(value.value)}
            onChange={(event) => changeRaw(event.target.value)}
            disabled={disabled}
            inputMode={literalType === 'number' ? 'decimal' : 'text'}
            aria-label="Literal value"
          />
        )}
      </div>
    </div>
  )
}

function ColumnFields({
  value,
  onChange,
  disabled,
}: {
  value: ColumnExpression
  onChange: (next: PlanExpression) => void
  disabled: boolean
}) {
  const datasetId = React.useId()
  const columnId = React.useId()
  return (
    <div className="grid grid-cols-2 gap-2">
      <div className="flex flex-col gap-1">
        <Label htmlFor={datasetId} className="text-xs text-muted-foreground">
          Dataset
        </Label>
        <Input
          id={datasetId}
          value={value.dataset}
          onChange={(event) =>
            onChange({ ...value, dataset: event.target.value })
          }
          disabled={disabled}
          placeholder="e.g. DM"
          aria-label="Column dataset"
        />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={columnId} className="text-xs text-muted-foreground">
          Column
        </Label>
        <Input
          id={columnId}
          value={value.column}
          onChange={(event) =>
            onChange({ ...value, column: event.target.value })
          }
          disabled={disabled}
          placeholder="e.g. AGE"
          aria-label="Column name"
        />
      </div>
    </div>
  )
}

function UnaryFields({
  value,
  onChange,
  disabled,
  depth,
}: {
  value: UnaryExpression
  onChange: (next: PlanExpression) => void
  disabled: boolean
  depth: number
}) {
  const operatorId = React.useId()
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-1">
        <Label htmlFor={operatorId} className="text-xs text-muted-foreground">
          Operator
        </Label>
        <Select
          value={value.operator}
          onValueChange={(next) =>
            onChange({ ...value, operator: next as UnaryExpression['operator'] })
          }
          disabled={disabled}
        >
          <SelectTrigger id={operatorId} size="sm" aria-label="Unary operator">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {UNARY_OPERATORS.map((operator) => (
              <SelectItem key={operator} value={operator}>
                {operator}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <ExpressionBuilder
        label="Operand"
        value={value.operand as PlanExpression}
        onChange={(next) => onChange({ ...value, operand: next })}
        disabled={disabled}
        depth={depth + 1}
      />
    </div>
  )
}

function BinaryFields({
  value,
  onChange,
  disabled,
  depth,
}: {
  value: BinaryExpression
  onChange: (next: PlanExpression) => void
  disabled: boolean
  depth: number
}) {
  const operatorId = React.useId()
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-1">
        <Label htmlFor={operatorId} className="text-xs text-muted-foreground">
          Operator
        </Label>
        <Select
          value={value.operator}
          onValueChange={(next) =>
            onChange({ ...value, operator: next as BinaryExpression['operator'] })
          }
          disabled={disabled}
        >
          <SelectTrigger id={operatorId} size="sm" aria-label="Binary operator">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {BINARY_OPERATORS.map((operator) => (
              <SelectItem key={operator} value={operator}>
                {operator}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <ExpressionBuilder
        label="Left"
        value={value.left as PlanExpression}
        onChange={(next) => onChange({ ...value, left: next })}
        disabled={disabled}
        depth={depth + 1}
      />
      <ExpressionBuilder
        label="Right"
        value={value.right as PlanExpression}
        onChange={(next) => onChange({ ...value, right: next })}
        disabled={disabled}
        depth={depth + 1}
      />
    </div>
  )
}

/**
 * A keyed list of structured expression assignments (`target column -> typed
 * expression`), used by the `derive` operator inspector. Entirely typed; the
 * only free text is the target column name and literal/column identifiers.
 */
export interface AssignmentListProps {
  assignments: Record<string, PlanExpression>
  onChange: (next: Record<string, PlanExpression>) => void
  disabled?: boolean
}

export function AssignmentList({
  assignments,
  onChange,
  disabled = false,
}: AssignmentListProps) {
  const entries = Object.entries(assignments)

  function rename(oldKey: string, newKey: string) {
    const next: Record<string, PlanExpression> = {}
    for (const [key, expr] of Object.entries(assignments)) {
      next[key === oldKey ? newKey : key] = expr
    }
    onChange(next)
  }

  function setExpression(key: string, expr: PlanExpression) {
    onChange({ ...assignments, [key]: expr })
  }

  function remove(key: string) {
    const next = { ...assignments }
    delete next[key]
    onChange(next)
  }

  function add() {
    const base = 'NEWVAR'
    let name = base
    let suffix = 1
    while (name in assignments) {
      name = `${base}${suffix}`
      suffix += 1
    }
    onChange({ ...assignments, [name]: defaultExpression('column') })
  }

  return (
    <div className="flex flex-col gap-3">
      {entries.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No assignments yet. Add a target column and build its typed expression.
        </p>
      )}
      {entries.map(([key, expr]) => (
        <div key={key} className="flex flex-col gap-2 rounded-md border p-2">
          <div className="flex items-end gap-2">
            <div className="flex flex-1 flex-col gap-1">
              <Label className="text-xs text-muted-foreground">
                Target column
              </Label>
              <Input
                value={key}
                onChange={(event) => rename(key, event.target.value)}
                disabled={disabled}
                aria-label="Assignment target column"
              />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => remove(key)}
              disabled={disabled}
              aria-label={`Remove assignment ${key}`}
            >
              <Trash2 className="size-4" aria-hidden />
            </Button>
          </div>
          <ExpressionBuilder
            value={expr}
            onChange={(next) => setExpression(key, next)}
            disabled={disabled}
          />
        </div>
      ))}
      <div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={add}
          disabled={disabled}
        >
          <Plus className="size-4" aria-hidden /> Add assignment
        </Button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Literal value helpers
// ---------------------------------------------------------------------------

type LiteralType = 'string' | 'number' | 'boolean' | 'null'

function literalTypeOf(value: LiteralExpression['value']): LiteralType {
  if (value === null) return 'null'
  if (typeof value === 'number') return 'number'
  if (typeof value === 'boolean') return 'boolean'
  return 'string'
}

function coerceLiteral(
  value: LiteralExpression['value'],
  nextType: LiteralType,
): LiteralExpression['value'] {
  switch (nextType) {
    case 'null':
      return null
    case 'boolean':
      return value === true || value === 'true'
    case 'number': {
      const parsed = Number(value)
      return Number.isFinite(parsed) ? parsed : 0
    }
    case 'string':
      return value == null ? '' : String(value)
  }
}

function parseLiteral(
  raw: string,
  type: LiteralType,
): LiteralExpression['value'] {
  if (type === 'number') {
    const parsed = Number(raw)
    return Number.isFinite(parsed) ? parsed : 0
  }
  return raw
}
