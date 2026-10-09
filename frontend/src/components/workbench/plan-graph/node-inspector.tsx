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
  CastOperationInvalid,
  CastOperationTargetType,
  JoinNodeJoinType,
  SdtmAggregationOperation,
  TerminologyMapNodeUnmapped,
} from '@/api/generated/model'
import type {
  AggregateNode,
  AssertNode,
  CastNode,
  DeriveNode,
  DomainWriteNode,
  FilterNode,
  JoinNode,
  PivotLongerNode,
  RawReadNode,
  SdtmDerivationPlanNodesItem,
  SelectNode,
  SequenceNode,
  SortNode,
  TerminologyMapNode,
} from '@/api/generated/model'

import { descriptorFor } from './operator-catalog'
import {
  AssignmentList,
  ExpressionBuilder,
  type PlanExpression,
} from './expression-builder'

/**
 * The node inspector binds the selected node's typed operator parameters,
 * directly to the `api/generated/model` shapes — never an untyped dictionary
 * and never a free-text code field. Each operator renders a small typed form;
 * `derive`/`filter`/`assert` use the structured {@link ExpressionBuilder}.
 */
export interface NodeInspectorProps {
  node: SdtmDerivationPlanNodesItem | null
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  /** Read-only mode (e.g. when the plan is misaligned) disables every field. */
  readOnly?: boolean
}

export function NodeInspector({
  node,
  onChange,
  readOnly = false,
}: NodeInspectorProps) {
  if (!node) {
    return (
      <div className="flex h-full flex-col gap-2 p-4" aria-live="polite">
        <h3 className="text-sm font-medium">Inspector</h3>
        <p className="text-sm text-muted-foreground">
          Select a node on the canvas to edit its typed parameters.
        </p>
      </div>
    )
  }

  const descriptor = descriptorFor(node)

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-medium">{descriptor.label}</h3>
        <p className="text-xs text-muted-foreground">{descriptor.description}</p>
        <p className="text-xs text-muted-foreground">
          id: <code>{node.id}</code>
        </p>
      </div>
      <NodeFields node={node} onChange={onChange} readOnly={readOnly} />
    </div>
  )
}

function NodeFields({
  node,
  onChange,
  readOnly,
}: {
  node: SdtmDerivationPlanNodesItem
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  readOnly: boolean
}) {
  switch (node.node_type) {
    case 'raw_read':
      return <RawReadFields node={node} onChange={onChange} readOnly={readOnly} />
    case 'select':
      return <SelectFields node={node} onChange={onChange} readOnly={readOnly} />
    case 'filter':
      return <FilterFields node={node} onChange={onChange} readOnly={readOnly} />
    case 'join':
      return <JoinFields node={node} onChange={onChange} readOnly={readOnly} />
    case 'union':
      return (
        <p className="text-sm text-muted-foreground">
          Union has no parameters; connect two or more inputs on the canvas.
        </p>
      )
    case 'cast':
      return <CastFields node={node} onChange={onChange} readOnly={readOnly} />
    case 'pivot_longer':
      return <PivotFields node={node} onChange={onChange} readOnly={readOnly} />
    case 'derive':
      return <DeriveFields node={node} onChange={onChange} readOnly={readOnly} />
    case 'terminology_map':
      return <TerminologyFields node={node} onChange={onChange} readOnly={readOnly} />
    case 'aggregate':
      return <AggregateFields node={node} onChange={onChange} readOnly={readOnly} />
    case 'sequence':
      return <SequenceFields node={node} onChange={onChange} readOnly={readOnly} />
    case 'sort':
      return <SortFields node={node} onChange={onChange} readOnly={readOnly} />
    case 'assert':
      return <AssertFields node={node} onChange={onChange} readOnly={readOnly} />
    case 'domain_write':
      return <DomainWriteFields node={node} onChange={onChange} readOnly={readOnly} />
  }
}

// ---------------------------------------------------------------------------
// Small reusable field pieces
// ---------------------------------------------------------------------------

function TextField({
  label,
  value,
  onChange,
  readOnly,
  placeholder,
}: {
  label: string
  value: string
  onChange: (next: string) => void
  readOnly: boolean
  placeholder?: string
}) {
  const id = React.useId()
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </Label>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={readOnly}
        placeholder={placeholder}
        aria-label={label}
      />
    </div>
  )
}

/** Editable list of free-standing string tokens (column names, keys, ...). */
function StringListField({
  label,
  values,
  onChange,
  readOnly,
  itemLabel = 'value',
}: {
  label: string
  values: string[]
  onChange: (next: string[]) => void
  readOnly: boolean
  itemLabel?: string
}) {
  function set(index: number, next: string) {
    onChange(values.map((value, i) => (i === index ? next : value)))
  }
  function remove(index: number) {
    onChange(values.filter((_, i) => i !== index))
  }
  function add() {
    onChange([...values, ''])
  }
  return (
    <div className="flex flex-col gap-2">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {values.map((value, index) => (
        <div key={index} className="flex items-center gap-2">
          <Input
            value={value}
            onChange={(event) => set(index, event.target.value)}
            disabled={readOnly}
            aria-label={`${itemLabel} ${index + 1}`}
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => remove(index)}
            disabled={readOnly}
            aria-label={`Remove ${itemLabel} ${index + 1}`}
          >
            <Trash2 className="size-4" aria-hidden />
          </Button>
        </div>
      ))}
      <div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={add}
          disabled={readOnly}
        >
          <Plus className="size-4" aria-hidden /> Add {itemLabel}
        </Button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Per-operator field groups
// ---------------------------------------------------------------------------

function RawReadFields({
  node,
  onChange,
  readOnly,
}: {
  node: RawReadNode
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  readOnly: boolean
}) {
  return (
    <TextField
      label="Raw dataset code"
      value={node.raw_dataset_code}
      onChange={(next) => onChange({ ...node, raw_dataset_code: next })}
      readOnly={readOnly}
      placeholder="e.g. DM"
    />
  )
}

function SelectFields({
  node,
  onChange,
  readOnly,
}: {
  node: SelectNode
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  readOnly: boolean
}) {
  return (
    <StringListField
      label="Columns to keep"
      values={node.columns}
      onChange={(next) => onChange({ ...node, columns: next })}
      readOnly={readOnly}
      itemLabel="column"
    />
  )
}

function FilterFields({
  node,
  onChange,
  readOnly,
}: {
  node: FilterNode
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  readOnly: boolean
}) {
  return (
    <div className="flex flex-col gap-2">
      <Label className="text-xs text-muted-foreground">Predicate</Label>
      <ExpressionBuilder
        value={node.predicate as PlanExpression}
        onChange={(next) => onChange({ ...node, predicate: next })}
        disabled={readOnly}
      />
    </div>
  )
}

function JoinFields({
  node,
  onChange,
  readOnly,
}: {
  node: JoinNode
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  readOnly: boolean
}) {
  const joinTypeId = React.useId()

  function setKey(index: number, side: 0 | 1, value: string) {
    const keys = node.keys.map((pair, i) => {
      if (i !== index) return pair
      const next: [string, string] = [pair[0], pair[1]]
      next[side] = value
      return next
    })
    onChange({ ...node, keys })
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <Label htmlFor={joinTypeId} className="text-xs text-muted-foreground">
          Join type
        </Label>
        <Select
          value={node.join_type}
          onValueChange={(next) =>
            onChange({ ...node, join_type: next as JoinNode['join_type'] })
          }
          disabled={readOnly}
        >
          <SelectTrigger id={joinTypeId} size="sm" aria-label="Join type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.values(JoinNodeJoinType).map((joinType) => (
              <SelectItem key={joinType} value={joinType}>
                {joinType}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-2">
        <Label className="text-xs text-muted-foreground">Key pairs (left, right)</Label>
        {node.keys.map((pair, index) => (
          <div key={index} className="flex items-center gap-2">
            <Input
              value={pair[0]}
              onChange={(event) => setKey(index, 0, event.target.value)}
              disabled={readOnly}
              aria-label={`Left key ${index + 1}`}
            />
            <Input
              value={pair[1]}
              onChange={(event) => setKey(index, 1, event.target.value)}
              disabled={readOnly}
              aria-label={`Right key ${index + 1}`}
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() =>
                onChange({ ...node, keys: node.keys.filter((_, i) => i !== index) })
              }
              disabled={readOnly}
              aria-label={`Remove key pair ${index + 1}`}
            >
              <Trash2 className="size-4" aria-hidden />
            </Button>
          </div>
        ))}
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onChange({ ...node, keys: [...node.keys, ['', '']] })}
            disabled={readOnly}
          >
            <Plus className="size-4" aria-hidden /> Add key pair
          </Button>
        </div>
      </div>

      <TextField
        label="Right suffix (optional)"
        value={node.right_suffix ?? ''}
        onChange={(next) =>
          onChange({ ...node, right_suffix: next === '' ? undefined : next })
        }
        readOnly={readOnly}
        placeholder="_R"
      />
    </div>
  )
}

function CastFields({
  node,
  onChange,
  readOnly,
}: {
  node: CastNode
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  readOnly: boolean
}) {
  const entries = Object.entries(node.casts)

  function rename(oldKey: string, newKey: string) {
    const next: CastNode['casts'] = {}
    for (const [key, op] of Object.entries(node.casts)) {
      next[key === oldKey ? newKey : key] = op
    }
    onChange({ ...node, casts: next })
  }
  function setTargetType(key: string, targetType: CastOperationTargetType) {
    onChange({
      ...node,
      casts: { ...node.casts, [key]: { ...node.casts[key], target_type: targetType } },
    })
  }
  function setSourceColumn(key: string, sourceColumn: string) {
    onChange({
      ...node,
      casts: {
        ...node.casts,
        [key]: { ...node.casts[key], source_column: sourceColumn },
      },
    })
  }
  function setInvalid(key: string, invalid: CastOperationInvalid) {
    onChange({
      ...node,
      casts: { ...node.casts, [key]: { ...node.casts[key], invalid } },
    })
  }
  function remove(key: string) {
    const next = { ...node.casts }
    delete next[key]
    onChange({ ...node, casts: next })
  }
  function add() {
    let name = 'col'
    let suffix = 1
    while (name in node.casts) {
      name = `col${suffix}`
      suffix += 1
    }
    onChange({
      ...node,
      casts: {
        ...node.casts,
        [name]: { source_column: '', target_type: 'text', invalid: 'error' },
      },
    })
  }

  return (
    <div className="flex flex-col gap-3">
      <Label className="text-xs text-muted-foreground">Casts (target column)</Label>
      {entries.map(([key, op]) => (
        <div key={key} className="flex flex-col gap-2 rounded-md border p-2">
          <TextField
            label="Target column"
            value={key}
            onChange={(next) => rename(key, next)}
            readOnly={readOnly}
          />
          <TextField
            label="Source column"
            value={op.source_column}
            onChange={(next) => setSourceColumn(key, next)}
            readOnly={readOnly}
          />
          <div className="grid grid-cols-2 gap-2">
            <EnumSelect
              label="Target type"
              value={op.target_type}
              options={Object.values(CastOperationTargetType)}
              onChange={(next) => setTargetType(key, next as CastOperationTargetType)}
              readOnly={readOnly}
            />
            <EnumSelect
              label="On invalid"
              value={op.invalid ?? 'error'}
              options={Object.values(CastOperationInvalid)}
              onChange={(next) => setInvalid(key, next as CastOperationInvalid)}
              readOnly={readOnly}
            />
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => remove(key)}
            disabled={readOnly}
            aria-label={`Remove cast ${key}`}
          >
            <Trash2 className="size-4" aria-hidden /> Remove
          </Button>
        </div>
      ))}
      <div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={add}
          disabled={readOnly}
        >
          <Plus className="size-4" aria-hidden /> Add cast
        </Button>
      </div>
    </div>
  )
}

function PivotFields({
  node,
  onChange,
  readOnly,
}: {
  node: PivotLongerNode
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  readOnly: boolean
}) {
  return (
    <div className="flex flex-col gap-3">
      <StringListField
        label="Id columns"
        values={node.id_columns}
        onChange={(next) => onChange({ ...node, id_columns: next })}
        readOnly={readOnly}
        itemLabel="id column"
      />
      <StringListField
        label="Value columns"
        values={node.value_columns}
        onChange={(next) => onChange({ ...node, value_columns: next })}
        readOnly={readOnly}
        itemLabel="value column"
      />
      <TextField
        label="Name column"
        value={node.name_column}
        onChange={(next) => onChange({ ...node, name_column: next })}
        readOnly={readOnly}
      />
      <TextField
        label="Value column"
        value={node.value_column}
        onChange={(next) => onChange({ ...node, value_column: next })}
        readOnly={readOnly}
      />
    </div>
  )
}

function DeriveFields({
  node,
  onChange,
  readOnly,
}: {
  node: DeriveNode
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  readOnly: boolean
}) {
  return (
    <div className="flex flex-col gap-3">
      <TextField
        label="Target domain"
        value={node.target_domain}
        onChange={(next) => onChange({ ...node, target_domain: next })}
        readOnly={readOnly}
        placeholder="e.g. DM"
      />
      <div className="flex flex-col gap-1">
        <Label className="text-xs text-muted-foreground">
          Assignments (structured typed expressions)
        </Label>
        <AssignmentList
          assignments={node.assignments as Record<string, PlanExpression>}
          onChange={(next) => onChange({ ...node, assignments: next })}
          disabled={readOnly}
        />
      </div>
    </div>
  )
}

function TerminologyFields({
  node,
  onChange,
  readOnly,
}: {
  node: TerminologyMapNode
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  readOnly: boolean
}) {
  const entries = Object.entries(node.mappings)

  function setMapping(from: string, to: string) {
    onChange({ ...node, mappings: { ...node.mappings, [from]: to } })
  }
  function renameFrom(oldFrom: string, newFrom: string) {
    const next: TerminologyMapNode['mappings'] = {}
    for (const [from, to] of Object.entries(node.mappings)) {
      next[from === oldFrom ? newFrom : from] = to
    }
    onChange({ ...node, mappings: next })
  }
  function remove(from: string) {
    const next = { ...node.mappings }
    delete next[from]
    onChange({ ...node, mappings: next })
  }

  return (
    <div className="flex flex-col gap-3">
      <TextField
        label="Source column"
        value={node.source_column}
        onChange={(next) => onChange({ ...node, source_column: next })}
        readOnly={readOnly}
      />
      <TextField
        label="Target column"
        value={node.target_column}
        onChange={(next) => onChange({ ...node, target_column: next })}
        readOnly={readOnly}
      />
      <EnumSelect
        label="Unmapped handling"
        value={node.unmapped ?? 'preserve'}
        options={Object.values(TerminologyMapNodeUnmapped)}
        onChange={(next) =>
          onChange({ ...node, unmapped: next as TerminologyMapNode['unmapped'] })
        }
        readOnly={readOnly}
      />
      <div className="flex flex-col gap-2">
        <Label className="text-xs text-muted-foreground">
          Mappings (source value -&gt; target value)
        </Label>
        {entries.map(([from, to], index) => (
          <div key={index} className="flex items-center gap-2">
            <Input
              value={from}
              onChange={(event) => renameFrom(from, event.target.value)}
              disabled={readOnly}
              aria-label={`Mapping source ${index + 1}`}
            />
            <Input
              value={to}
              onChange={(event) => setMapping(from, event.target.value)}
              disabled={readOnly}
              aria-label={`Mapping target ${index + 1}`}
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => remove(from)}
              disabled={readOnly}
              aria-label={`Remove mapping ${index + 1}`}
            >
              <Trash2 className="size-4" aria-hidden />
            </Button>
          </div>
        ))}
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setMapping('', '')}
            disabled={readOnly}
          >
            <Plus className="size-4" aria-hidden /> Add mapping
          </Button>
        </div>
      </div>
    </div>
  )
}

function AggregateFields({
  node,
  onChange,
  readOnly,
}: {
  node: AggregateNode
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  readOnly: boolean
}) {
  const entries = Object.entries(node.aggregations)

  function renameTarget(oldKey: string, newKey: string) {
    const next: AggregateNode['aggregations'] = {}
    for (const [key, agg] of Object.entries(node.aggregations)) {
      next[key === oldKey ? newKey : key] = agg
    }
    onChange({ ...node, aggregations: next })
  }
  function setOperation(key: string, operation: SdtmAggregationOperation) {
    onChange({
      ...node,
      aggregations: {
        ...node.aggregations,
        [key]: { ...node.aggregations[key], operation },
      },
    })
  }
  function setColumn(key: string, column: string) {
    onChange({
      ...node,
      aggregations: {
        ...node.aggregations,
        [key]: { ...node.aggregations[key], column: column === '' ? null : column },
      },
    })
  }

  return (
    <div className="flex flex-col gap-3">
      <StringListField
        label="Group by"
        values={node.group_by}
        onChange={(next) => onChange({ ...node, group_by: next })}
        readOnly={readOnly}
        itemLabel="group column"
      />
      <Label className="text-xs text-muted-foreground">Aggregations (target column)</Label>
      {entries.map(([key, agg]) => (
        <div key={key} className="flex flex-col gap-2 rounded-md border p-2">
          <TextField
            label="Target column"
            value={key}
            onChange={(next) => renameTarget(key, next)}
            readOnly={readOnly}
          />
          <div className="grid grid-cols-2 gap-2">
            <EnumSelect
              label="Operation"
              value={agg.operation}
              options={Object.values(SdtmAggregationOperation)}
              onChange={(next) => setOperation(key, next as SdtmAggregationOperation)}
              readOnly={readOnly}
            />
            <TextField
              label="Source column"
              value={agg.column ?? ''}
              onChange={(next) => setColumn(key, next)}
              readOnly={readOnly}
            />
          </div>
        </div>
      ))}
      <div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            onChange({
              ...node,
              aggregations: {
                ...node.aggregations,
                [`AGG${entries.length + 1}`]: { operation: 'count', column: null },
              },
            })
          }
          disabled={readOnly}
        >
          <Plus className="size-4" aria-hidden /> Add aggregation
        </Button>
      </div>
    </div>
  )
}

function SequenceFields({
  node,
  onChange,
  readOnly,
}: {
  node: SequenceNode
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  readOnly: boolean
}) {
  const startId = React.useId()
  return (
    <div className="flex flex-col gap-3">
      <TextField
        label="Target column"
        value={node.target_column}
        onChange={(next) => onChange({ ...node, target_column: next })}
        readOnly={readOnly}
      />
      <StringListField
        label="Group by (optional)"
        values={node.group_by ?? []}
        onChange={(next) =>
          onChange({ ...node, group_by: next.length === 0 ? undefined : next })
        }
        readOnly={readOnly}
        itemLabel="group column"
      />
      <StringListField
        label="Order by"
        values={node.order_by}
        onChange={(next) => onChange({ ...node, order_by: next })}
        readOnly={readOnly}
        itemLabel="order column"
      />
      <div className="flex flex-col gap-1">
        <Label htmlFor={startId} className="text-xs text-muted-foreground">
          Start (optional)
        </Label>
        <Input
          id={startId}
          type="number"
          min={0}
          value={node.start ?? ''}
          onChange={(event) => {
            const raw = event.target.value
            onChange({
              ...node,
              start: raw === '' ? undefined : Math.max(0, Number(raw)),
            })
          }}
          disabled={readOnly}
          aria-label="Sequence start"
        />
      </div>
    </div>
  )
}

function SortFields({
  node,
  onChange,
  readOnly,
}: {
  node: SortNode
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  readOnly: boolean
}) {
  return (
    <StringListField
      label="Sort keys"
      values={node.keys}
      onChange={(next) => onChange({ ...node, keys: next })}
      readOnly={readOnly}
      itemLabel="sort key"
    />
  )
}

function AssertFields({
  node,
  onChange,
  readOnly,
}: {
  node: AssertNode
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  readOnly: boolean
}) {
  return (
    <div className="flex flex-col gap-3">
      <TextField
        label="Issue code"
        value={node.issue_code}
        onChange={(next) => onChange({ ...node, issue_code: next })}
        readOnly={readOnly}
        placeholder="e.g. SDTM_SEQ_GAP"
      />
      <div className="flex flex-col gap-2">
        <Label className="text-xs text-muted-foreground">Predicate</Label>
        <ExpressionBuilder
          value={node.predicate as PlanExpression}
          onChange={(next) => onChange({ ...node, predicate: next })}
          disabled={readOnly}
        />
      </div>
    </div>
  )
}

function DomainWriteFields({
  node,
  onChange,
  readOnly,
}: {
  node: DomainWriteNode
  onChange: (next: SdtmDerivationPlanNodesItem) => void
  readOnly: boolean
}) {
  return (
    <TextField
      label="Domain"
      value={node.domain}
      onChange={(next) => onChange({ ...node, domain: next })}
      readOnly={readOnly}
      placeholder="e.g. DM"
    />
  )
}

function EnumSelect({
  label,
  value,
  options,
  onChange,
  readOnly,
}: {
  label: string
  value: string
  options: readonly string[]
  onChange: (next: string) => void
  readOnly: boolean
}) {
  const id = React.useId()
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </Label>
      <Select value={value} onValueChange={onChange} disabled={readOnly}>
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
