import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(iso?: string | null): string {
  if (iso == null) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString()
}

export function formatBytes(n?: number | null): string {
  if (n == null || Number.isNaN(n)) return '—'
  if (n === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const exponent = Math.min(
    Math.floor(Math.log(Math.abs(n)) / Math.log(1024)),
    units.length - 1,
  )
  const value = n / Math.pow(1024, exponent)
  const formatted = exponent === 0 ? String(value) : value.toFixed(1)
  return `${formatted} ${units[exponent]}`
}
