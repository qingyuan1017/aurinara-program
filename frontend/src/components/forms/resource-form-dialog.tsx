import * as React from 'react'
import type { AxiosError } from 'axios'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  FormControl,
  FormDescription,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from '@/components/ui/sonner'
import { mapProblemToFieldErrors, stalenessAlert } from '@/lib/problems'

export type FieldControl = 'text' | 'textarea' | 'select' | 'multiselect' | 'tags' | 'number'

export interface FieldDescriptor<TBody> {
  name: keyof TBody & string
  label: string
  control: FieldControl
  required?: boolean
  placeholder?: string
  options?: { label: string; value: string }[]
  helpText?: string
  maxLength?: number
  pattern?: { re: RegExp; message: string }
  min?: number
  max?: number
}

export interface ResourceFormDialogProps<TBody extends object> {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  fields: FieldDescriptor<TBody>[]
  initialValues: Partial<TBody>
  submitLabel?: string
  /** Receives ONLY the validated body. The screen wraps path ids. */
  onSubmit: (body: TBody) => Promise<unknown>
  isSubmitting: boolean
  submitError: AxiosError | null
  successMessage: string
}

type FormValue = string | number | string[] | undefined
type FormState = Record<string, FormValue>

function toFormState<TBody>(
  fields: FieldDescriptor<TBody>[],
  initial: Partial<TBody>,
): FormState {
  const state: FormState = {}
  for (const field of fields) {
    const raw = (initial as Record<string, unknown>)[field.name]
    if (field.control === 'tags' || field.control === 'multiselect') {
      state[field.name] = Array.isArray(raw) ? (raw as string[]) : []
    } else if (field.control === 'number') {
      state[field.name] = typeof raw === 'number' ? raw : undefined
    } else {
      state[field.name] = raw == null ? '' : String(raw)
    }
  }
  return state
}

function isEmpty(value: FormValue): boolean {
  if (value == null) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  return false
}

export function ResourceFormDialog<TBody extends object>({
  open,
  onOpenChange,
  title,
  description,
  fields,
  initialValues,
  submitLabel = 'Save',
  onSubmit,
  isSubmitting,
  submitError,
  successMessage,
}: ResourceFormDialogProps<TBody>) {
  const [values, setValues] = React.useState<FormState>(() =>
    toFormState(fields, initialValues),
  )
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>(
    {},
  )
  const [formErrors, setFormErrors] = React.useState<string[]>([])

  // Re-seed on open so edit prefills and create resets.
  React.useEffect(() => {
    if (open) {
      setValues(toFormState(fields, initialValues))
      setFieldErrors({})
      setFormErrors([])
    }
    // Intentionally keyed on `open`; initialValues is captured at open time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // Surface a hook error that arrives outside the submit flow (e.g. the screen
  // sets it imperatively). The submit flow's own catch distributes errors first.
  React.useEffect(() => {
    if (!submitError) return
    const stale = stalenessAlert(submitError)
    if (stale) {
      setFormErrors((prev) => (prev.length ? prev : [stale]))
      return
    }
    const mapped = mapProblemToFieldErrors(
      submitError,
      fields.map((f) => f.name),
    )
    setFieldErrors((prev) =>
      Object.keys(prev).length ? prev : mapped.fieldErrors,
    )
    setFormErrors((prev) => (prev.length ? prev : mapped.formErrors))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [submitError])

  function setFieldValue(name: string, value: FormValue) {
    setValues((prev) => ({ ...prev, [name]: value }))
    setFieldErrors((prev) => {
      if (!prev[name]) return prev
      const next = { ...prev }
      delete next[name]
      return next
    })
  }

  function validate(): Record<string, string> {
    const errors: Record<string, string> = {}
    for (const field of fields) {
      const value = values[field.name]
      if (field.required && isEmpty(value)) {
        errors[field.name] = `${field.label} is required.`
        continue
      }
      if (isEmpty(value)) continue
      if (typeof value === 'string') {
        if (field.maxLength && value.length > field.maxLength) {
          errors[field.name] =
            `${field.label} must be at most ${field.maxLength} characters.`
          continue
        }
        if (field.pattern && !field.pattern.re.test(value)) {
          errors[field.name] = field.pattern.message
          continue
        }
      }
      if (field.control === 'number' && typeof value === 'number') {
        if (field.min != null && value < field.min) {
          errors[field.name] = `${field.label} must be at least ${field.min}.`
          continue
        }
        if (field.max != null && value > field.max) {
          errors[field.name] = `${field.label} must be at most ${field.max}.`
          continue
        }
      }
    }
    return errors
  }

  function buildBody(): TBody {
    const body: Record<string, unknown> = {}
    for (const field of fields) {
      const value = values[field.name]
      // Drop empty optionals so PATCH stays sparse (exclude_unset on backend).
      if (!field.required && isEmpty(value)) continue
      if (field.control === 'tags' || field.control === 'multiselect') {
        body[field.name] = Array.isArray(value) ? value : []
      } else if (field.control === 'number') {
        body[field.name] = value
      } else {
        body[field.name] = value
      }
    }
    return body as TBody
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const errors = validate()
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors)
      return
    }
    setFieldErrors({})
    setFormErrors([])
    try {
      await onSubmit(buildBody())
      toast.success(successMessage)
      onOpenChange(false)
    } catch (error) {
      const axiosError = error as AxiosError
      const stale = stalenessAlert(axiosError)
      if (stale) {
        setFormErrors([stale])
        return
      }
      const mapped = mapProblemToFieldErrors(
        axiosError,
        fields.map((f) => f.name),
      )
      setFieldErrors(mapped.fieldErrors)
      setFormErrors(mapped.formErrors)
    }
  }

  const hasFieldErrors = Object.keys(fieldErrors).length > 0

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!isSubmitting) onOpenChange(next)
      }}
    >
      <DialogContent>
        <form onSubmit={handleSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description && (
              <DialogDescription>{description}</DialogDescription>
            )}
          </DialogHeader>

          {formErrors.length > 0 && (
            <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm">
              {formErrors.map((message, index) => (
                <p key={index}>{message}</p>
              ))}
            </div>
          )}

          <div className="grid gap-4">
            {fields.map((field) => {
              const id = `field-${field.name}`
              const error = fieldErrors[field.name]
              const value = values[field.name]
              return (
                <FormItem key={field.name}>
                  <FormLabel htmlFor={id}>
                    {field.label}
                    {field.required && (
                      <span className="text-destructive"> *</span>
                    )}
                  </FormLabel>
                  <FormControl>
                    {field.control === 'textarea' ? (
                      <Textarea
                        id={id}
                        value={typeof value === 'string' ? value : ''}
                        placeholder={field.placeholder}
                        aria-invalid={!!error}
                        onChange={(e) =>
                          setFieldValue(field.name, e.target.value)
                        }
                      />
                    ) : field.control === 'select' ? (
                      <Select
                        value={typeof value === 'string' ? value : ''}
                        onValueChange={(v) => setFieldValue(field.name, v)}
                      >
                        <SelectTrigger id={id} className="w-full">
                          <SelectValue
                            placeholder={field.placeholder ?? 'Select…'}
                          />
                        </SelectTrigger>
                        <SelectContent>
                          {field.options?.map((option) => (
                            <SelectItem
                              key={option.value}
                              value={option.value}
                            >
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : field.control === 'multiselect' ? (
                      <div id={id} className="max-h-48 space-y-1 overflow-y-auto rounded-md border p-2" aria-invalid={!!error}>
                        {field.options?.length ? field.options.map((option) => {
                          const selected = Array.isArray(value) && value.includes(option.value)
                          return (
                            <label key={option.value} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-muted">
                              <input
                                type="checkbox"
                                checked={selected}
                                onChange={(event) => {
                                  const current = Array.isArray(value) ? value : []
                                  setFieldValue(field.name, event.target.checked
                                    ? [...current, option.value]
                                    : current.filter((item) => item !== option.value))
                                }}
                              />
                              <span>{option.label}</span>
                            </label>
                          )
                        }) : <p className="px-2 py-1 text-sm text-muted-foreground">No options available.</p>}
                      </div>
                    ) : field.control === 'tags' ? (
                      <Input
                        id={id}
                        value={Array.isArray(value) ? value.join(', ') : ''}
                        placeholder={field.placeholder ?? 'Comma-separated'}
                        aria-invalid={!!error}
                        onChange={(e) =>
                          setFieldValue(
                            field.name,
                            e.target.value
                              .split(',')
                              .map((item) => item.trim())
                              .filter((item) => item.length > 0),
                          )
                        }
                      />
                    ) : field.control === 'number' ? (
                      <Input
                        id={id}
                        type="number"
                        value={typeof value === 'number' ? value : ''}
                        placeholder={field.placeholder}
                        min={field.min}
                        max={field.max}
                        aria-invalid={!!error}
                        onChange={(e) =>
                          setFieldValue(
                            field.name,
                            e.target.value === ''
                              ? undefined
                              : Number(e.target.value),
                          )
                        }
                      />
                    ) : (
                      <Input
                        id={id}
                        value={typeof value === 'string' ? value : ''}
                        placeholder={field.placeholder}
                        aria-invalid={!!error}
                        onChange={(e) =>
                          setFieldValue(field.name, e.target.value)
                        }
                      />
                    )}
                  </FormControl>
                  {field.helpText && !error && (
                    <FormDescription>{field.helpText}</FormDescription>
                  )}
                  <FormMessage>{error}</FormMessage>
                </FormItem>
              )
            })}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={isSubmitting}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || hasFieldErrors}>
              {isSubmitting && <Loader2 className="animate-spin" />}
              {isSubmitting ? 'Saving…' : submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
