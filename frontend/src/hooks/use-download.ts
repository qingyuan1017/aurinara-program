import { useCallback, useState } from 'react'
import type { AxiosResponse } from 'axios'
import { AXIOS_INSTANCE } from '@/api/axios-instance'

/**
 * `useDownload` — the single escape hatch for backend bodies the Orval typed
 * client cannot model as a typed JSON response (Requirement 1.4):
 *
 * - Specification export: `GET /api/v1/sdtms/{sdtmId}/specification/export?format=json|xlsx`
 *   (Requirement 11.6)
 * - Artifact download: `GET /api/v1/artifacts/{artifactId}/download` (Requirement 8.4)
 * - Define render: `GET /api/v1/sdtms/{sdtmId}/define/render?version=2.0|2.1` (Requirement 18.5)
 *
 * It calls {@link AXIOS_INSTANCE} directly with `responseType: 'blob'`, so it
 * inherits the exact base URL and the bearer-token request interceptor applied
 * to every generated hook — it never hand-rolls auth or the API prefix.
 *
 * Binary bodies (artifact downloads, XLSX/JSON Specification exports) are saved
 * through a transient object-URL anchor. The Define render is returned as text
 * for a non-persisting XML preview rather than forced to disk.
 */

export type SpecificationExportFormat = 'json' | 'xlsx'
export type DefineRenderVersion = '2.0' | '2.1'

/** Shape of the async state surfaced to callers. */
export interface DownloadState {
  /** True while any download/render request is in flight. */
  isPending: boolean
  /** The error from the most recent failed request, if any. */
  error: unknown
}

export interface UseDownloadResult extends DownloadState {
  /**
   * Export the SDTM Specification and save it to the user's device.
   *
   * @param sdtmId - The SDTM workbench id.
   * @param format - Restricted to exactly `json` or `xlsx` (Requirement 11.6).
   */
  downloadSpecificationExport: (
    sdtmId: string,
    format: SpecificationExportFormat,
  ) => Promise<void>
  /**
   * Download an immutable artifact by id and save it to the user's device
   * (Requirement 8.4). The server-provided `Content-Disposition` filename is
   * honored when present.
   *
   * @param artifactId - The artifact id.
   * @param fallbackFilename - Name used when the response carries no filename.
   */
  downloadArtifact: (artifactId: string, fallbackFilename?: string) => Promise<void>
  /**
   * Render Define-XML and return it as text for a non-persisting preview
   * (Requirement 18.5). Nothing is written to disk.
   *
   * @param sdtmId - The SDTM workbench id.
   * @param version - Restricted to exactly `2.0` or `2.1`.
   * @returns The rendered XML as a string.
   */
  renderDefineXml: (sdtmId: string, version: DefineRenderVersion) => Promise<string>
}

const CONTENT_DISPOSITION_FILENAME =
  /filename\*?=(?:UTF-8''|"?)([^";]+)"?/i

/** Pull a filename out of a `Content-Disposition` header when present. */
function filenameFromResponse(response: AxiosResponse<Blob>): string | undefined {
  const disposition = response.headers['content-disposition']
  if (typeof disposition !== 'string') {
    return undefined
  }
  const match = CONTENT_DISPOSITION_FILENAME.exec(disposition)
  if (!match?.[1]) {
    return undefined
  }
  try {
    return decodeURIComponent(match[1].trim())
  } catch {
    return match[1].trim()
  }
}

/**
 * Save a blob to the user's device via a transient object-URL anchor. The
 * object URL is always revoked, even if the click handler throws.
 */
function saveBlob(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = filename
    anchor.rel = 'noopener'
    anchor.style.display = 'none'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  } finally {
    URL.revokeObjectURL(objectUrl)
  }
}

export function useDownload(): UseDownloadResult {
  const [isPending, setIsPending] = useState(false)
  const [error, setError] = useState<unknown>(null)

  /** Run a blob request, tracking pending/error state uniformly. */
  const requestBlob = useCallback(
    async (
      url: string,
      params?: Record<string, string>,
    ): Promise<AxiosResponse<Blob>> => {
      setIsPending(true)
      setError(null)
      try {
        return await AXIOS_INSTANCE.get<Blob>(url, {
          responseType: 'blob',
          params,
        })
      } catch (err) {
        setError(err)
        throw err
      } finally {
        setIsPending(false)
      }
    },
    [],
  )

  const downloadSpecificationExport = useCallback(
    async (sdtmId: string, format: SpecificationExportFormat): Promise<void> => {
      const response = await requestBlob(
        `/api/v1/sdtms/${sdtmId}/specification/export`,
        { format },
      )
      const filename =
        filenameFromResponse(response) ?? `specification-${sdtmId}.${format}`
      saveBlob(response.data, filename)
    },
    [requestBlob],
  )

  const downloadArtifact = useCallback(
    async (artifactId: string, fallbackFilename?: string): Promise<void> => {
      const response = await requestBlob(`/api/v1/artifacts/${artifactId}/download`)
      const filename =
        filenameFromResponse(response) ?? fallbackFilename ?? artifactId
      saveBlob(response.data, filename)
    },
    [requestBlob],
  )

  const renderDefineXml = useCallback(
    async (sdtmId: string, version: DefineRenderVersion): Promise<string> => {
      const response = await requestBlob(`/api/v1/sdtms/${sdtmId}/define/render`, {
        version,
      })
      return response.data.text()
    },
    [requestBlob],
  )

  return {
    isPending,
    error,
    downloadSpecificationExport,
    downloadArtifact,
    renderDefineXml,
  }
}

export default useDownload
