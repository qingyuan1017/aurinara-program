import * as React from 'react'
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  Copy,
  Plus,
  Search,
  Trash2,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  BinaryExpressionOperator,
  CastExpressionInvalid,
  CastExpressionTargetType,
  FunctionCallExpressionFunction,
  TerminologyMapExpressionUnmapped,
  UnaryExpressionOperator,
} from '@/api/generated/model'
import type {
  BinaryExpression,
  CastExpression,
  ColumnExpression,
  ConditionalBranch,
  ConditionalExpression,
  CustomFunctionDefinition,
  CustomFunctionCallExpression,
  FunctionCallExpression,
  ListLiteralExpression,
  ListLiteralExpressionValuesItem,
  LiteralExpression,
  TerminologyMapExpression,
  UnaryExpression,
} from '@/api/generated/model'
import {
  FUNCTION_CATALOG,
  FUNCTION_CATEGORIES,
  functionParameter,
  type FunctionName,
} from './function-catalog'

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
  | CustomFunctionCallExpression
  | CastExpression
  | TerminologyMapExpression

export type NestedPlanExpression = Exclude<
  PlanExpression,
  CastExpression | TerminologyMapExpression
>

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
  { value: 'custom_function', label: 'Custom function' },
  { value: 'cast', label: 'Cast function' },
  { value: 'terminology_map', label: 'Terminology mapping function' },
]

const BINARY_OPERATORS = Object.values(BinaryExpressionOperator)
const UNARY_OPERATORS = Object.values(UnaryExpressionOperator)
const FUNCTION_NAMES = Object.values(FunctionCallExpressionFunction)

const CustomFunctionsContext = React.createContext<readonly CustomFunctionDefinition[]>([])

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
    case 'custom_function':
      return {
        kind: 'custom_function',
        function_id: '',
        arguments: [{ kind: 'column', dataset: '', column: '' }],
      }
    case 'cast':
      return {
        kind: 'cast',
        value: { kind: 'column', dataset: '', column: '' },
        target_type: 'text',
        invalid: 'error',
      }
    case 'terminology_map':
      return {
        kind: 'terminology_map',
        value: { kind: 'column', dataset: '', column: '' },
        mappings: { source: 'target' },
        unmapped: 'error',
      }
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
  const min = FUNCTION_CATALOG[fn].parameters.length
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
  /** Offer SDTM cast and terminology functions for derivation assignments. */
  allowDerivationFunctions?: boolean
  /** Named custom functions declared by the containing plan. */
  customFunctions?: readonly CustomFunctionDefinition[]
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
  allowDerivationFunctions = false,
  customFunctions,
}: ExpressionBuilderProps) {
  const kindId = React.useId()
  const inheritedCustomFunctions = React.useContext(CustomFunctionsContext)
  const availableCustomFunctions = customFunctions ?? inheritedCustomFunctions

  function changeKind(kind: ExpressionKind) {
    if (kind === value.kind) return
    onChange(defaultExpression(kind))
  }

  return (
    <CustomFunctionsContext.Provider value={availableCustomFunctions}>
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
            {KIND_OPTIONS.filter(
              (option) =>
                allowDerivationFunctions ||
                (option.value !== 'cast' && option.value !== 'terminology_map'),
            ).map((option) => (
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
      {value.kind === 'custom_function' && (
        <CustomFunctionFields
          value={value}
          onChange={onChange}
          disabled={disabled}
          depth={depth}
        />
      )}
      {value.kind === 'cast' && (
        <CastFunctionFields
          value={value}
          onChange={onChange}
          disabled={disabled}
          depth={depth}
        />
      )}
      {value.kind === 'terminology_map' && (
        <TerminologyFunctionFields
          value={value}
          onChange={onChange}
          disabled={disabled}
          depth={depth}
        />
      )}
    </div>
    </CustomFunctionsContext.Provider>
  )
}

function CastFunctionFields({
  value,
  onChange,
  disabled,
  depth,
}: {
  value: CastExpression
  onChange: (next: PlanExpression) => void
  disabled: boolean
  depth: number
}) {
  return (
    <div className="flex flex-col gap-2" data-slot="cast-function-fields">
      <ExpressionBuilder
        value={value.value as PlanExpression}
        onChange={(next) =>
          onChange({ ...value, value: next as NestedPlanExpression })
        }
        disabled={disabled}
        depth={depth + 1}
        label="Value to cast"
      />
      <div className="grid grid-cols-2 gap-2">
        <EnumField
          label="Target type"
          value={value.target_type}
          options={Object.values(CastExpressionTargetType)}
          onChange={(next) =>
            onChange({
              ...value,
              target_type: next as CastExpression['target_type'],
            })
          }
          disabled={disabled}
        />
        <EnumField
          label="On invalid"
          value={value.invalid ?? 'error'}
          options={Object.values(CastExpressionInvalid)}
          onChange={(next) =>
            onChange({ ...value, invalid: next as CastExpression['invalid'] })
          }
          disabled={disabled}
        />
      </div>
    </div>
  )
}

function TerminologyFunctionFields({
  value,
  onChange,
  disabled,
  depth,
}: {
  value: TerminologyMapExpression
  onChange: (next: PlanExpression) => void
  disabled: boolean
  depth: number
}) {
  const entries = Object.entries(value.mappings)

  function renameSource(previous: string, next: string) {
    const mappings: Record<string, string> = {}
    for (const [source, target] of entries) {
      mappings[source === previous ? next : source] = target
    }
    onChange({ ...value, mappings })
  }

  function setTarget(source: string, target: string) {
    onChange({ ...value, mappings: { ...value.mappings, [source]: target } })
  }

  function remove(source: string) {
    const mappings = { ...value.mappings }
    delete mappings[source]
    onChange({ ...value, mappings })
  }

  function add() {
    let source = 'source'
    let suffix = 1
    while (source in value.mappings) {
      source = `source${suffix}`
      suffix += 1
    }
    onChange({ ...value, mappings: { ...value.mappings, [source]: 'target' } })
  }

  return (
    <div className="flex flex-col gap-2" data-slot="terminology-function-fields">
      <ExpressionBuilder
        value={value.value as PlanExpression}
        onChange={(next) =>
          onChange({ ...value, value: next as NestedPlanExpression })
        }
        disabled={disabled}
        depth={depth + 1}
        label="Value to map"
      />
      <EnumField
        label="Unmapped handling"
        value={value.unmapped ?? 'error'}
        options={Object.values(TerminologyMapExpressionUnmapped)}
        onChange={(next) =>
          onChange({
            ...value,
            unmapped: next as TerminologyMapExpression['unmapped'],
          })
        }
        disabled={disabled}
      />
      <Label className="text-xs text-muted-foreground">
        Mappings (source value → controlled value)
      </Label>
      {entries.map(([source, target], index) => (
        <div key={`${source}-${index}`} className="flex items-center gap-2">
          <Input
            value={source}
            onChange={(event) => renameSource(source, event.target.value)}
            disabled={disabled}
            aria-label={`Terminology source ${index + 1}`}
          />
          <Input
            value={target}
            onChange={(event) => setTarget(source, event.target.value)}
            disabled={disabled}
            aria-label={`Terminology target ${index + 1}`}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => remove(source)}
            disabled={disabled || entries.length === 1}
            aria-label={`Remove terminology mapping ${index + 1}`}
          >
            <Trash2 />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-fit"
        onClick={add}
        disabled={disabled}
      >
        <Plus /> Add mapping
      </Button>
    </div>
  )
}

function EnumField({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string
  value: string
  options: readonly string[]
  onChange: (next: string) => void
  disabled: boolean
}) {
  const id = React.useId()
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </Label>
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger id={id} size="sm" aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function CustomFunctionFields({
  value,
  onChange,
  disabled,
  depth,
}: {
  value: CustomFunctionCallExpression
  onChange: (next: PlanExpression) => void
  disabled: boolean
  depth: number
}) {
  const functionId = React.useId()
  const customFunctions = React.useContext(CustomFunctionsContext)
  const definition = customFunctions.find((item) => item.id === value.function_id)

  function changeFunction(nextId: string) {
    const nextDefinition = customFunctions.find((item) => item.id === nextId)
    onChange({
      ...value,
      function_id: nextId,
      arguments: nextDefinition
        ? nextDefinition.parameters.map(() => ({
            kind: 'column' as const,
            dataset: '',
            column: '',
          }))
        : value.arguments,
    })
  }

  function setArgument(
    index: number,
    next: CustomFunctionCallExpression['arguments'][number],
  ) {
    const arguments_ = [...value.arguments]
    arguments_[index] = next
    onChange({ ...value, arguments: arguments_ })
  }

  return (
    <div className="flex flex-col gap-2" data-slot="custom-function-fields">
      <div className="flex flex-col gap-1">
        <Label htmlFor={functionId} className="text-xs text-muted-foreground">
          Custom function
        </Label>
        {customFunctions.length > 0 ? (
          <Select
            value={value.function_id}
            onValueChange={changeFunction}
            disabled={disabled}
          >
            <SelectTrigger id={functionId} size="sm" aria-label="Custom function">
              <SelectValue placeholder="Select a declared function" />
            </SelectTrigger>
            <SelectContent>
              {customFunctions.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  {item.id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <p className="rounded-md border border-dashed p-2 text-xs text-muted-foreground">
            Declare a custom function above the graph before using it in a recipe.
          </p>
        )}
      </div>
      {definition && definition.parameters.length !== value.arguments.length && (
        <div className="flex items-center justify-between rounded-md border border-destructive/50 p-2 text-xs text-destructive">
          <span>
            Signature requires {definition.parameters.length} parameter{definition.parameters.length === 1 ? '' : 's'}.
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => changeFunction(definition.id)}
            disabled={disabled}
          >
            Sync parameters
          </Button>
        </div>
      )}
      {value.arguments.map((argument, index) => (
        <div key={index} className="flex flex-col gap-1">
          <div className="min-w-0 flex-1">
            <ExpressionBuilder
              value={argument as PlanExpression}
              onChange={(next) => setArgument(index, next as NestedPlanExpression)}
              disabled={disabled}
              depth={depth + 1}
              label={definition?.parameters[index] ?? `argument ${index + 1}`}
            />
          </div>
          {!definition && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="w-fit"
              onClick={() =>
                onChange({
                  ...value,
                  arguments: value.arguments.filter((_, item) => item !== index),
                })
              }
              disabled={disabled}
              aria-label={`Remove custom function argument ${index + 1}`}
            >
              <Trash2 /> Remove argument
            </Button>
          )}
        </div>
      ))}
      {!definition && customFunctions.length === 0 && (
        <p className="text-xs text-muted-foreground">
          Argument controls will follow the declared parameter names and arity.
        </p>
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
        onChange={(next) =>
          onChange({ ...value, operand: next as NestedPlanExpression })
        }
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
        onChange={(next) =>
          onChange({ ...value, left: next as NestedPlanExpression })
        }
        disabled={disabled}
        depth={depth + 1}
      />
      <ExpressionBuilder
        label="Right"
        value={value.right as PlanExpression}
        onChange={(next) =>
          onChange({ ...value, right: next as NestedPlanExpression })
        }
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
            onChange={(next) =>
              setBranch(index, { ...branch, when: next as NestedPlanExpression })
            }
            disabled={disabled}
            depth={depth + 1}
          />
          <ExpressionBuilder
            label="Then"
            value={branch.then as PlanExpression}
            onChange={(next) =>
              setBranch(index, { ...branch, then: next as NestedPlanExpression })
            }
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
        onChange={(next) =>
          onChange({ ...value, otherwise: next as NestedPlanExpression })
        }
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
  const descriptor = FUNCTION_CATALOG[value.function]
  const minimum = descriptor.parameters.length

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
    if (args.length <= minimum) return
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
            {FUNCTION_CATEGORIES.map((category, categoryIndex) => (
              <React.Fragment key={category}>
                {categoryIndex > 0 && <SelectSeparator />}
                <SelectGroup>
                  <SelectLabel>{category}</SelectLabel>
                  {FUNCTION_NAMES.filter(
                    (name) => FUNCTION_CATALOG[name].category === category,
                  ).map((name) => (
                    <SelectItem key={name} value={name}>
                      {name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </React.Fragment>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">{descriptor.description}</p>
      </div>

      {args.map((arg, index) => {
        const isListSlot = value.function === 'is_in' && index === 1
        const parameter = functionParameter(value.function, index)
        return (
          <div
            key={index}
            className="flex flex-col gap-1"
            data-slot="function-argument"
          >
            <div className="flex items-center justify-between">
              <Label className="text-xs text-muted-foreground">
                {parameter.name}
              </Label>
              {descriptor.variadic && args.length > minimum && (
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
                label={parameter.name}
                value={arg as PlanExpression}
                onChange={(next) => setArgument(index, next as NestedPlanExpression)}
                disabled={disabled}
                depth={depth + 1}
              />
            )}
            <p className="text-xs text-muted-foreground">
              {parameter.description}
            </p>
          </div>
        )
      })}

      {descriptor.variadic && (
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addArgument}
            disabled={disabled}
            aria-label="Add argument"
          >
            <Plus className="size-4" aria-hidden /> Add value
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
  targetDomain?: string
  customFunctions?: readonly CustomFunctionDefinition[]
}

export function AssignmentList({
  assignments,
  onChange,
  disabled = false,
  targetDomain = '',
  customFunctions = [],
}: AssignmentListProps) {
  const entries = Object.entries(assignments)
  const [search, setSearch] = React.useState('')
  const normalizedSearch = search.trim().toUpperCase()
  const visibleEntries = entries.filter(([target, expression]) =>
    `${target} ${expressionSummary(expression)}`.toUpperCase().includes(normalizedSearch),
  )
  const dependencyMap = assignmentDependencies(assignments, targetDomain)
  const cyclicTargets = cyclicAssignments(dependencyMap)

  function rename(oldKey: string, newKey: string) {
    if (newKey !== oldKey && newKey in assignments) return
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

  function duplicate(key: string) {
    const base = `${key}_COPY`
    let name = base
    let suffix = 2
    while (name in assignments) {
      name = `${base}${suffix}`
      suffix += 1
    }
    const next: Record<string, PlanExpression> = {}
    for (const [target, expression] of entries) {
      next[target] = expression
      if (target === key) {
        next[name] = JSON.parse(JSON.stringify(expression)) as PlanExpression
      }
    }
    onChange(next)
  }

  function move(key: string, offset: -1 | 1) {
    const index = entries.findIndex(([target]) => target === key)
    const destination = index + offset
    if (index < 0 || destination < 0 || destination >= entries.length) return
    const reordered = [...entries]
    ;[reordered[index], reordered[destination]] = [
      reordered[destination],
      reordered[index],
    ]
    onChange(Object.fromEntries(reordered))
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
      {entries.length > 3 && (
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground"
            aria-hidden
          />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="pl-8"
            placeholder="Find a target variable or function"
            aria-label="Search derived variables"
          />
        </div>
      )}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{entries.length} variable recipe{entries.length === 1 ? '' : 's'}</span>
        <span>Evaluated top to bottom</span>
      </div>
      {entries.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No assignments yet. Add a target column and build its typed expression.
        </p>
      )}
      {normalizedSearch && visibleEntries.length === 0 && (
        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
          No variable recipes match “{search}”.
        </p>
      )}
      {visibleEntries.map(([key, expr]) => {
        const index = entries.findIndex(([target]) => target === key)
        const dependencies = dependencyMap.get(key) ?? []
        const laterDependencies = dependencies.filter(
          (dependency) => entries.findIndex(([target]) => target === dependency) > index,
        )
        return (
          <VariableRecipeCard
            key={index}
            target={key}
            expression={expr}
            index={index}
            count={entries.length}
            dependencies={dependencies}
            laterDependencies={laterDependencies}
            cyclic={cyclicTargets.has(key)}
            configured={expressionConfigured(expr, customFunctions)}
            disabled={disabled}
            customFunctions={customFunctions}
            onRename={(next) => rename(key, next)}
            onExpressionChange={(next) => setExpression(key, next)}
            onDuplicate={() => duplicate(key)}
            onRemove={() => remove(key)}
            onMove={move}
          />
        )
      })}
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

function VariableRecipeCard({
  target,
  expression,
  index,
  count,
  dependencies,
  laterDependencies,
  cyclic,
  configured,
  disabled,
  customFunctions,
  onRename,
  onExpressionChange,
  onDuplicate,
  onRemove,
  onMove,
}: {
  target: string
  expression: PlanExpression
  index: number
  count: number
  dependencies: string[]
  laterDependencies: string[]
  cyclic: boolean
  configured: boolean
  disabled: boolean
  customFunctions: readonly CustomFunctionDefinition[]
  onRename: (next: string) => void
  onExpressionChange: (next: PlanExpression) => void
  onDuplicate: () => void
  onRemove: () => void
  onMove: (key: string, offset: -1 | 1) => void
}) {
  const [expanded, setExpanded] = React.useState(true)
  const hasDependencyIssue = cyclic || laterDependencies.length > 0

  return (
    <section className="rounded-md border" data-slot="variable-recipe">
      <div className="flex items-center gap-1 border-b p-2">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={() => setExpanded((current) => !current)}
          aria-label={`${expanded ? 'Collapse' : 'Expand'} ${target}`}
        >
          {expanded ? <ChevronDown /> : <ChevronRight />}
        </Button>
        <div className="min-w-0 flex-1">
          <Input
            value={target}
            onChange={(event) => onRename(event.target.value)}
            disabled={disabled}
            aria-label="Assignment target column"
            className="font-mono font-medium"
          />
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {expressionSummary(expression)}
          </p>
        </div>
        <div className="flex items-center gap-0.5">
          <Button type="button" variant="ghost" size="icon" onClick={() => onMove(target, -1)} disabled={disabled || index === 0} aria-label={`Move ${target} up`}>
            <ArrowUp />
          </Button>
          <Button type="button" variant="ghost" size="icon" onClick={() => onMove(target, 1)} disabled={disabled || index === count - 1} aria-label={`Move ${target} down`}>
            <ArrowDown />
          </Button>
          <Button type="button" variant="ghost" size="icon" onClick={onDuplicate} disabled={disabled} aria-label={`Duplicate assignment ${target}`}>
            <Copy />
          </Button>
          <Button type="button" variant="ghost" size="icon" onClick={onRemove} disabled={disabled || count === 1} aria-label={`Remove assignment ${target}`}>
            <Trash2 />
          </Button>
        </div>
      </div>
      <div className="flex flex-wrap gap-1 px-2 pt-2">
        <Badge variant={configured ? 'secondary' : 'destructive'}>
          {configured ? 'Configured' : 'Needs attention'}
        </Badge>
        {dependencies.map((dependency) => (
          <Badge key={dependency} variant="outline">uses {dependency}</Badge>
        ))}
        {hasDependencyIssue && (
          <Badge variant="destructive">
            {cyclic ? 'Circular dependency' : `Move ${laterDependencies.join(', ')} earlier`}
          </Badge>
        )}
      </div>
      {expanded && (
        <div className="p-2">
          <ExpressionBuilder
            value={expression}
            onChange={onExpressionChange}
            disabled={disabled}
            allowDerivationFunctions
            customFunctions={customFunctions}
          />
        </div>
      )}
    </section>
  )
}

function expressionSummary(expression: PlanExpression): string {
  switch (expression.kind) {
    case 'literal':
      return expression.value === null ? 'missing value' : `constant ${String(expression.value)}`
    case 'column':
      return `${expression.dataset || '?'}.${expression.column || '?'}`
    case 'unary':
      return `${expression.operator}(${expressionSummary(expression.operand as PlanExpression)})`
    case 'binary':
      return `${expression.operator}(${expressionSummary(expression.left as PlanExpression)}, ${expressionSummary(expression.right as PlanExpression)})`
    case 'conditional':
      return `conditional with ${expression.branches.length} branch${expression.branches.length === 1 ? '' : 'es'}`
    case 'function':
      return `${expression.function}(${expression.arguments.length} parameter${expression.arguments.length === 1 ? '' : 's'})`
    case 'custom_function':
      return `${expression.function_id || 'custom function'}(${expression.arguments.length} parameter${expression.arguments.length === 1 ? '' : 's'})`
    case 'cast':
      return `cast to ${expression.target_type}`
    case 'terminology_map':
      return `terminology map (${Object.keys(expression.mappings).length} entries)`
  }
}

function nestedExpressions(expression: PlanExpression): PlanExpression[] {
  switch (expression.kind) {
    case 'unary':
      return [expression.operand as PlanExpression]
    case 'binary':
      return [expression.left as PlanExpression, expression.right as PlanExpression]
    case 'conditional':
      return [
        ...expression.branches.flatMap((branch) => [
          branch.when as PlanExpression,
          branch.then as PlanExpression,
        ]),
        expression.otherwise as PlanExpression,
      ]
    case 'function':
    case 'custom_function':
      return expression.arguments.filter(
        (argument) => argument.kind !== 'list_literal',
      ) as PlanExpression[]
    case 'cast':
    case 'terminology_map':
      return [expression.value as PlanExpression]
    default:
      return []
  }
}

function expressionConfigured(
  expression: PlanExpression,
  customFunctions: readonly CustomFunctionDefinition[],
): boolean {
  if (expression.kind === 'column') {
    return expression.dataset.trim().length > 0 && expression.column.trim().length > 0
  }
  if (expression.kind === 'custom_function') {
    const definition = customFunctions.find((item) => item.id === expression.function_id)
    if (!definition || definition.parameters.length !== expression.arguments.length) return false
  }
  if (expression.kind === 'terminology_map' && Object.keys(expression.mappings).some((key) => !key.trim())) {
    return false
  }
  return nestedExpressions(expression).every((child) =>
    expressionConfigured(child, customFunctions),
  )
}

function assignmentDependencies(
  assignments: Record<string, PlanExpression>,
  targetDomain: string,
): Map<string, string[]> {
  const targets = new Set(Object.keys(assignments))
  const result = new Map<string, string[]>()
  for (const [target, expression] of Object.entries(assignments)) {
    const dependencies = new Set<string>()
    const visit = (candidate: PlanExpression) => {
      if (
        candidate.kind === 'column' &&
        candidate.dataset === targetDomain &&
        targets.has(candidate.column)
      ) {
        dependencies.add(candidate.column)
      }
      nestedExpressions(candidate).forEach(visit)
    }
    visit(expression)
    result.set(target, [...dependencies])
  }
  return result
}

function cyclicAssignments(dependencies: Map<string, string[]>): Set<string> {
  const cyclic = new Set<string>()
  const visited = new Set<string>()
  const active: string[] = []
  const visit = (target: string) => {
    const activeIndex = active.indexOf(target)
    if (activeIndex >= 0) {
      active.slice(activeIndex).forEach((item) => cyclic.add(item))
      return
    }
    if (visited.has(target)) return
    active.push(target)
    for (const dependency of dependencies.get(target) ?? []) visit(dependency)
    active.pop()
    visited.add(target)
  }
  dependencies.forEach((_, target) => visit(target))
  return cyclic
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
