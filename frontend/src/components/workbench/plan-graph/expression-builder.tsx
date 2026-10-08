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
  FunctionCallExpressionFunction,
  UnaryExpressionOperator,
} from '@/api/generated/model'
import type {
  BinaryExpression,
  ColumnExpression,
  ConditionalBranch,
  ConditionalExpression,
  FunctionCallExpression,
  ListLiteralExpression,
  ListLiteralExpressionValuesItem,
  LiteralExpression,
  UnaryExpression,
} from '@/api/generated/model'

/**
 * A structured, strictly typed expression editor used by the `derive`, `filter`
 * and `assert` operator inspectors.
 *
 * It builds the generated `LiteralExpression | ColumnExpression |
 * UnaryExpression | BinaryExpression | ConditionalExpression |
 * FunctionCallExpression` union recursively and NEVER exposes a free-text
 * Python/R/SAS/SQL field — the operator, expression kind and function name are
 * chosen from fixed selects, and the only free text is a literal value, a
 * column/dataset identifier or an individual list-literal member. This is the
 * platform boundary that keeps raw code strings out of the authoring model
 * (AGENTS.md "Compilation and execution").
 */
export type PlanExpression =
  | LiteralExpression
  | ColumnExpression
  | UnaryExpression
  | BinaryExpression
  | ConditionalExpression
  | FunctionCallExpression

/**
 * The selectable kinds. `list_literal` is deliberately NOT offered here: it is
 * only valid as the second argument of the `is_in` function and is rendered by
 * a dedicated typed value-list editor in {@link FunctionFields}. Surfacing it
 * as a general kind would let it be placed where the backend rejects it.
 */
type ExpressionKind = PlanExpression['kind']

const KIND_OPTIONS: { value: ExpressionKind; label: string }[] = [
  { value: 'column', label: 'Column' },
  { value: 'literal', label: 'Literal value' },
  { value: 'unary', label: 'Unary operation' },
  { value: 'binary', label: 'Binary operation' },
  { value: 'conditional', label: 'Conditional (case/when)' },
  { value: 'function', label: 'Function' },
]

const BINARY_OPERATORS = Object.values(BinaryExpressionOperator)
const UNARY_OPERATORS = Object.values(UnaryExpressionOperator)
const FUNCTION_NAMES = Object.values(FunctionCallExpressionFunction)

type FunctionName = FunctionCallExpression['function']

/**
 * Per-function positional arity, mirroring the backend `FunctionCallExpression`
 * `model_validator`. Variadic functions declare their MINIMUM count; the editor
 * lets the author add further arguments beyond it. Fixed-arity functions pin an
 * exact count. Changing the function resets the argument list to this arity so
 * the author never submits a structurally invalid call.
 */
const FUNCTION_ARITY: Record<FunctionName, { min: number; variadic: boolean }> =
  {
    // variadic (minimum count)
    concat: { min: 1, variadic: true },
    coalesce: { min: 1, variadic: true },
    min_of: { min: 1, variadic: true },
    max_of: { min: 1, variadic: true },
    n_missing: { min: 1, variadic: true },
    n_present: { min: 1, variadic: true },
    // fixed arity
    substring: { min: 3, variadic: false },
    upper: { min: 1, variadic: false },
    lower: { min: 1, variadic: false },
    trim: { min: 1, variadic: false },
    length: { min: 1, variadic: false },
    contains: { min: 2, variadic: false },
    startswith: { min: 2, variadic: false },
    endswith: { min: 2, variadic: false },
    replace: { min: 3, variadic: false },
    index_of: { min: 2, variadic: false },
    scan_token: { min: 3, variadic: false },
    pad_left: { min: 3, variadic: false },
    pad_right: { min: 3, variadic: false },
    nullif: { min: 2, variadic: false },
    is_in: { min: 2, variadic: false },
    round: { min: 2, variadic: false },
    floor: { min: 1, variadic: false },
    ceil: { min: 1, variadic: false },
    abs: { min: 1, variadic: false },
    modulo: { min: 2, variadic: false },
    truncate: { min: 1, variadic: false },
    safe_divide: { min: 2, variadic: false },
    parse_date: { min: 1, variadic: false },
    year: { min: 1, variadic: false },
    month: { min: 1, variadic: false },
    day: { min: 1, variadic: false },
    date_diff_days: { min: 2, variadic: false },
    parse_datetime: { min: 1, variadic: false },
    hour: { min: 1, variadic: false },
    minute: { min: 1, variadic: false },
    second: { min: 1, variadic: false },
    study_day: { min: 2, variadic: false },
    date_add_days: { min: 2, variadic: false },
    date_diff_months: { min: 2, variadic: false },
  }

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
    case 'conditional':
      return {
        kind: 'conditional',
        branches: [
          {
            when: { kind: 'column', dataset: '', column: '' },
            then: { kind: 'literal', value: '' },
          },
        ],
        otherwise: { kind: 'literal', value: null },
      }
    case 'function':
      // A safe default: `upper` applied to a single column argument.
      return defaultFunction('upper')
  }
}

/** A fresh default `list_literal` with one empty-string member. */
function defaultListLiteral(): ListLiteralExpression {
  return { kind: 'list_literal', values: [''] }
}

/**
 * A fresh default argument for a function argument slot. The `is_in` function
 * requires its 2nd argument to be a typed `list_literal`; every other slot is a
 * normal expression (defaulting to a column reference).
 */
function defaultArgument(
  fn: FunctionName,
  index: number,
): FunctionCallExpression['arguments'][number] {
  if (fn === 'is_in' && index === 1) {
    return defaultListLiteral()
  }
  return { kind: 'column', dataset: '', column: '' }
}

/** A fresh default `function` call for the given name at its minimum arity. */
function defaultFunction(fn: FunctionName): FunctionCallExpression {
  const { min } = FUNCTION_ARITY[fn]
  const args: FunctionCallExpression['arguments'] = []
  for (let i = 0; i < min; i += 1) {
    args.push(defaultArgument(fn, i))
  }
  return { kind: 'function', function: fn, arguments: args }
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
      {value.kind === 'conditional' && (
        <ConditionalFields
          value={value}
          onChange={onChange}
          disabled={disabled}
          depth={depth}
        />
      )}
      {value.kind === 'function' && (
        <FunctionFields
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
 * Editor for a multi-branch conditional (case/when). Each branch is a `When`
 * guard and a `Then` value, both built with the recursive {@link
 * ExpressionBuilder}; a single mandatory `Otherwise` closes the conditional.
 * No level renders a free-text code field.
 */
function ConditionalFields({
  value,
  onChange,
  disabled,
  depth,
}: {
  value: ConditionalExpression
  onChange: (next: PlanExpression) => void
  disabled: boolean
  depth: number
}) {
  const branches = value.branches as ConditionalBranch[]

  function setBranch(index: number, next: ConditionalBranch) {
    const nextBranches = branches.map((branch, i) =>
      i === index ? next : branch,
    )
    onChange({ ...value, branches: nextBranches })
  }

  function addBranch() {
    onChange({
      ...value,
      branches: [
        ...branches,
        {
          when: { kind: 'column', dataset: '', column: '' },
          then: { kind: 'literal', value: '' },
        },
      ],
    })
  }

  function removeBranch(index: number) {
    // Keep at least one branch (the backend enforces min_length >= 1).
    if (branches.length <= 1) return
    onChange({
      ...value,
      branches: branches.filter((_, i) => i !== index),
    })
  }

  return (
    <div className="flex flex-col gap-3" data-slot="conditional-fields">
      {branches.map((branch, index) => (
        <div
          key={index}
          className="flex flex-col gap-2 rounded-md border p-2"
          data-slot="conditional-branch"
        >
          <div className="flex items-center justify-between">
            <Label className="text-xs text-muted-foreground">
              Branch {index + 1}
            </Label>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => removeBranch(index)}
              disabled={disabled || branches.length <= 1}
              aria-label={`Remove branch ${index + 1}`}
            >
              <Trash2 className="size-4" aria-hidden />
            </Button>
          </div>
          <ExpressionBuilder
            label="When"
            value={branch.when as PlanExpression}
            onChange={(next) => setBranch(index, { ...branch, when: next })}
            disabled={disabled}
            depth={depth + 1}
          />
          <ExpressionBuilder
            label="Then"
            value={branch.then as PlanExpression}
            onChange={(next) => setBranch(index, { ...branch, then: next })}
            disabled={disabled}
            depth={depth + 1}
          />
        </div>
      ))}
      <div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addBranch}
          disabled={disabled}
        >
          <Plus className="size-4" aria-hidden /> Add branch
        </Button>
      </div>
      <ExpressionBuilder
        label="Otherwise"
        value={value.otherwise as PlanExpression}
        onChange={(next) => onChange({ ...value, otherwise: next })}
        disabled={disabled}
        depth={depth + 1}
      />
    </div>
  )
}

/**
 * Editor for a typed function call. The function is chosen from the generated
 * {@link FunctionCallExpressionFunction} allowlist, and each positional
 * argument is built with the recursive {@link ExpressionBuilder}. Changing the
 * function resets the arguments to the new function's arity. The `is_in`
 * function renders its 2nd argument as a typed value-list editor; variadic
 * functions allow adding/removing trailing arguments. There is never a
 * free-text code field.
 */
function FunctionFields({
  value,
  onChange,
  disabled,
  depth,
}: {
  value: FunctionCallExpression
  onChange: (next: PlanExpression) => void
  disabled: boolean
  depth: number
}) {
  const functionId = React.useId()
  const args = value.arguments as FunctionCallExpression['arguments']
  const arity = FUNCTION_ARITY[value.function]

  function changeFunction(fn: FunctionName) {
    if (fn === value.function) return
    // Arity-aware reset: rebuild the argument list for the new function so a
    // fixed-arity function always has exactly its arguments and `is_in` gets a
    // typed list literal in slot 2.
    onChange(defaultFunction(fn))
  }

  function setArgument(
    index: number,
    next: FunctionCallExpression['arguments'][number],
  ) {
    const nextArgs = args.map((arg, i) => (i === index ? next : arg))
    onChange({ ...value, arguments: nextArgs })
  }

  function addArgument() {
    onChange({
      ...value,
      arguments: [...args, defaultArgument(value.function, args.length)],
    })
  }

  function removeArgument(index: number) {
    if (args.length <= arity.min) return
    onChange({
      ...value,
      arguments: args.filter((_, i) => i !== index),
    })
  }

  return (
    <div className="flex flex-col gap-2" data-slot="function-fields">
      <div className="flex flex-col gap-1">
        <Label htmlFor={functionId} className="text-xs text-muted-foreground">
          Function
        </Label>
        <Select
          value={value.function}
          onValueChange={(next) => changeFunction(next as FunctionName)}
          disabled={disabled}
        >
          <SelectTrigger id={functionId} size="sm" aria-label="Function name">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FUNCTION_NAMES.map((name) => (
              <SelectItem key={name} value={name}>
                {name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {args.map((arg, index) => {
        const isListSlot = value.function === 'is_in' && index === 1
        return (
          <div
            key={index}
            className="flex flex-col gap-1"
            data-slot="function-argument"
          >
            <div className="flex items-center justify-between">
              <Label className="text-xs text-muted-foreground">
                Argument {index + 1}
              </Label>
              {arity.variadic && args.length > arity.min && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => removeArgument(index)}
                  disabled={disabled}
                  aria-label={`Remove argument ${index + 1}`}
                >
                  <Trash2 className="size-4" aria-hidden />
                </Button>
              )}
            </div>
            {isListSlot && arg.kind === 'list_literal' ? (
              <ListLiteralFields
                value={arg}
                onChange={(next) => setArgument(index, next)}
                disabled={disabled}
              />
            ) : (
              <ExpressionBuilder
                label={`Argument ${index + 1}`}
                value={arg as PlanExpression}
                onChange={(next) => setArgument(index, next)}
                disabled={disabled}
                depth={depth + 1}
              />
            )}
          </div>
        )
      })}

      {arity.variadic && (
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addArgument}
            disabled={disabled}
          >
            <Plus className="size-4" aria-hidden /> Add argument
          </Button>
        </div>
      )}
    </div>
  )
}

/**
 * A typed value-list editor for the `is_in` list-literal argument. Each member
 * is an individual typed literal value (text / number / boolean / null) — never
 * a free-text code expression. At least one member is kept (the backend
 * enforces min_length >= 1).
 */
function ListLiteralFields({
  value,
  onChange,
  disabled,
}: {
  value: ListLiteralExpression
  onChange: (next: ListLiteralExpression) => void
  disabled: boolean
}) {
  const members = value.values as ListLiteralExpressionValuesItem[]

  function setMember(index: number, next: ListLiteralExpressionValuesItem) {
    onChange({
      ...value,
      values: members.map((member, i) => (i === index ? next : member)),
    })
  }

  function addMember() {
    onChange({ ...value, values: [...members, ''] })
  }

  function removeMember(index: number) {
    if (members.length <= 1) return
    onChange({ ...value, values: members.filter((_, i) => i !== index) })
  }

  return (
    <div className="flex flex-col gap-2" data-slot="list-literal-fields">
      {members.map((member, index) => {
        const memberType = literalTypeOf(member)
        return (
          <div key={index} className="flex items-end gap-2">
            <div className="flex w-28 flex-col gap-1">
              <Label className="text-xs text-muted-foreground">Type</Label>
              <Select
                value={memberType}
                onValueChange={(next) =>
                  setMember(index, coerceLiteral(member, next as LiteralType))
                }
                disabled={disabled}
              >
                <SelectTrigger size="sm" aria-label={`Member ${index + 1} type`}>
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
            <div className="flex flex-1 flex-col gap-1">
              <Label className="text-xs text-muted-foreground">Value</Label>
              {memberType === 'boolean' ? (
                <Select
                  value={String(member === true)}
                  onValueChange={(next) => setMember(index, next === 'true')}
                  disabled={disabled}
                >
                  <SelectTrigger
                    size="sm"
                    aria-label={`Member ${index + 1} value`}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="true">true</SelectItem>
                    <SelectItem value="false">false</SelectItem>
                  </SelectContent>
                </Select>
              ) : memberType === 'null' ? (
                <Input
                  value="null"
                  disabled
                  readOnly
                  aria-label={`Member ${index + 1} value`}
                />
              ) : (
                <Input
                  value={member == null ? '' : String(member)}
                  onChange={(event) =>
                    setMember(index, parseLiteral(event.target.value, memberType))
                  }
                  disabled={disabled}
                  inputMode={memberType === 'number' ? 'decimal' : 'text'}
                  aria-label={`Member ${index + 1} value`}
                />
              )}
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => removeMember(index)}
              disabled={disabled || members.length <= 1}
              aria-label={`Remove member ${index + 1}`}
            >
              <Trash2 className="size-4" aria-hidden />
            </Button>
          </div>
        )
      })}
      <div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addMember}
          disabled={disabled}
        >
          <Plus className="size-4" aria-hidden /> Add value
        </Button>
      </div>
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
