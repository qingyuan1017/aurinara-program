import * as React from 'react'
import type { AxiosError, AxiosRequestConfig } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { Download, LibraryBig, Loader2, Save, Upload } from 'lucide-react'
import { toast } from 'sonner'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState, ErrorState } from '@/components/data/states'
import { IssueList } from '@/components/data/issue-list'
import { FileDropzone } from '@/components/workbench/file-dropzone'
import { SpecificationAuthoringCard } from '@/components/workbench/specification-authoring-card'
import { useWorkbench } from '@/components/workbench/workbench-context'
import { useDownload } from '@/hooks/use-download'
import { useIdempotencyKey } from '@/lib/requests'
import { parseProblem, stalenessAlert } from '@/lib/problems'
import {
  invalidateSdtmDependencies,
  invalidateSdtmSubResource,
} from '@/lib/invalidate'
import {
  getGetSpecificationInitializationOptionsQueryKey,
  getGetSpecificationQueryKey,
  useGetSdtmDependencies,
  useGetSpecification,
  useGetSpecificationInitializationOptions,
  useImportSpecification,
  useInitializeSpecification,
  usePutSpecification,
  useReplaceSdtmDependencies,
} from '@/api/generated/sdtm/sdtm'
import {
  useGetStandardVersion,
  useListStandards,
  useListStandardVersions,
} from '@/api/generated/provider-catalogs/provider-catalogs'
import type {
  DependencySelectionInput,
  SdtmDomain,
  SdtmSpecification,
  SdtmSpecificationInitialize,
  SdtmStandardDomainOption,
  SpecificationResponse,
  StandardVersionResponse,
} from '@/api/generated/model'

/**
 * SDTM Specification panel (Requirements 11.1-11.7).
 *
 * - View the current Specification revision + schema version from
 *   `GET /specification`; a `404 sdtm_specification_required` renders an
 *   unsaved empty state (11.1, 11.2).
 * - Create, edit, delete, and order domains and variables in a local draft,
 *   then save the whole Specification via `PUT /specification` with the SDTM
 *   workbench ETag as `If-Match` (11.3, 11.4).
 * - Import a Specification file via {@link FileDropzone} through
 *   `POST /specification/import` carrying the aggregate ETag and a stable
 *   `Idempotency-Key`; a `422 sdtm_specification_import_invalid` renders the
 *   problem `detail` + `issues[]` (11.4, 11.5).
 * - Export the Specification as `json`/`xlsx` via {@link useDownload} (11.6).
 * - A `412` on save surfaces a concurrency message and a reload action that
 *   re-fetches the current Specification revision before a retry (11.7).
 */
export function SpecificationPanel({ sdtmId }: { sdtmId: string }) {
  const qc = useQueryClient()
  const { ifMatch } = useWorkbench()
  const download = useDownload()
  const importKey = useIdempotencyKey()

  const specKey = React.useMemo(
    () => getGetSpecificationQueryKey(sdtmId),
    [sdtmId],
  )

  // View current Specification. The generated 404 is surfaced as an AxiosError;
  // `sdtm_specification_required` is the "not yet authored" signal, which the
  // panel renders as an unsaved empty state rather than an error (11.1, 11.2).
  const query = useGetSpecification(sdtmId)
  const spec = query.data
  const dependencies = useGetSdtmDependencies(sdtmId)
  const selectedStandard = dependencies.data?.standards?.find(
    (item) => item.purpose === 'sdtm_ig',
  ) ?? dependencies.data?.standards?.find(
    (item) => item.purpose === 'reference_metadata',
  )
  const standardProducts = useListStandards({
    family: 'SDTMIG',
    product_type: 'implementation_guide',
    scope: 'clinical',
  })
  const selectedStandardVersion = useGetStandardVersion(
    selectedStandard?.standard_version_id ?? '',
  )
  const [standardProductId, setStandardProductId] = React.useState('')
  const [standardVersionId, setStandardVersionId] = React.useState('')
  const standardVersions = useListStandardVersions(
    standardProductId,
    { module: 'sdtm' },
  )
  const canLoadInitializationOptions =
    !!selectedStandard?.standard_version_id &&
    standardVersionId === selectedStandard.standard_version_id
  const initializationOptions = useGetSpecificationInitializationOptions(
    sdtmId,
    { query: { enabled: canLoadInitializationOptions } },
  )
  const initializationOptionsMatch =
    initializationOptions.data?.standard_version_id ===
    selectedStandard?.standard_version_id
  const standardCatalogProblem = standardProducts.isError
    ? parseProblem(standardProducts.error as AxiosError).detail ??
      'Could not load the Standards catalog.'
    : standardVersions.isError
      ? parseProblem(standardVersions.error as AxiosError).detail ??
        'Could not load implementation-guide versions.'
      : null
  const initializationOptionsProblem =
    canLoadInitializationOptions && initializationOptions.isError
    ? parseProblem(initializationOptions.error as AxiosError).detail ??
      'Could not load domains from the selected implementation guide.'
    : null

  React.useEffect(() => {
    if (!selectedStandard?.standard_version_id || !selectedStandardVersion.data) {
      return
    }
    setStandardProductId(selectedStandardVersion.data.product_id)
    setStandardVersionId(selectedStandard.standard_version_id)
  }, [selectedStandard?.standard_version_id, selectedStandardVersion.data])

  React.useEffect(() => {
    const products = standardProducts.data ?? []
    if (!standardProductId && products.length === 1) {
      setStandardProductId(products[0].id)
    }
  }, [standardProductId, standardProducts.data])

  // The in-memory Specification draft. Seeded from the loaded payload and
  // re-seeded whenever the server revision changes (e.g. after save, import, or
  // a 412 reload) so domain/variable CRUD always starts from the latest revision
  // before the user stages another atomic save (11.3, 11.4, 11.7).
  const [domains, setDomains] = React.useState<SdtmDomain[]>([])
  const seededRevision = React.useRef<number | null>(null)

  React.useEffect(() => {
    if (!spec) return
    if (seededRevision.current === spec.revision) return
    seededRevision.current = spec.revision
    setDomains(domainsFromPayload(spec.payload))
  }, [spec])

  // A persistent concurrency notice shown after a 412 on save. Cleared when the
  // user reloads the current Specification revision before retrying (11.7).
  const [concurrency, setConcurrency] = React.useState<string | null>(null)
  const [importProblem, setImportProblem] = React.useState<AxiosError | null>(
    null,
  )
  const [initializeProblem, setInitializeProblem] = React.useState<string | null>(null)
  const [standardSelectionProblem, setStandardSelectionProblem] = React.useState<
    string | null
  >(null)

  const put = usePutSpecification({
    mutation: {
      onSuccess: () => invalidateSdtmSubResource(qc, 'specification', sdtmId),
    },
    request: ifMatch(),
  })
  const initialize = useInitializeSpecification({ request: ifMatch() })
  const replaceDependencies = useReplaceSdtmDependencies({
    mutation: {
      onSuccess: () => {
        invalidateSdtmDependencies(qc, sdtmId)
        void qc.invalidateQueries({
          queryKey: getGetSpecificationInitializationOptionsQueryKey(sdtmId),
        })
      },
    },
    request: ifMatch(),
  })

  async function handleSaveStandardSelection() {
    const version = standardVersions.data?.find(
      (item) => item.id === standardVersionId,
    )
    if (!version || !dependencies.data) return

    setStandardSelectionProblem(null)
    const purpose = version.purposes.includes('sdtm_ig')
      ? 'sdtm_ig'
      : 'reference_metadata'
    const body: DependencySelectionInput = {
      standards: [
        ...(dependencies.data.standards ?? []).filter(
          (item) =>
            item.purpose !== 'sdtm_ig' &&
            item.purpose !== 'reference_metadata',
        ),
        { purpose, standard_version_id: version.id },
      ],
      terminology: dependencies.data.terminology ?? [],
      references: dependencies.data.references ?? [],
      templates: dependencies.data.templates ?? [],
    }

    try {
      await replaceDependencies.mutateAsync({ sdtmId, data: body })
      toast.success('SDTM industry standard selection saved.')
    } catch (error) {
      const err = error as AxiosError
      if (err.response?.status === 412) {
        invalidateSdtmDependencies(qc, sdtmId)
      }
      setStandardSelectionProblem(
        stalenessAlert(err) ??
          parseProblem(err).detail ??
          err.message ??
          'Could not save the industry standard selection.',
      )
    }
  }

  async function handleInitialize(command: SdtmSpecificationInitialize) {
    setConcurrency(null)
    setInitializeProblem(null)
    try {
      const result = await initialize.mutateAsync({ sdtmId, data: command })
      seededRevision.current = null
      setDomains(domainsFromPayload(result.payload))
      await invalidateSdtmSubResource(qc, 'specification', sdtmId)
      toast.success('Specification populated from the selected industry standard.')
    } catch (error) {
      const err = error as AxiosError
      if (err.response?.status === 412) {
        setConcurrency(
          stalenessAlert(err) ??
            'This workbench changed since you opened it. Reload and try again.',
        )
        return
      }
      setInitializeProblem(
        parseProblem(err).detail ??
          err.message ??
          'Could not populate the Specification from the selected standard.',
      )
    }
  }

  // Import carries a dynamic per-attempt request (the raw file bytes, the
  // content type inferred from the file, the aggregate ETag, and a stable
  // Idempotency-Key). The generated hook only forwards a hook-level `request`
  // to the mutator, so the config is held in a ref read when the hook is
  // instantiated and the mutation is fired from an effect once a re-render has
  // picked up the pending config (keeping JSON/XLSX branching + headers intact).
  const importRequestRef = React.useRef<AxiosRequestConfig | undefined>(
    undefined,
  )
  const [pendingImport, setPendingImport] = React.useState<File | null>(null)
  const importSpec = useImportSpecification({
    request: importRequestRef.current,
  })

  const status = query.error?.response?.status
  const notFoundCode =
    status === 404 ? parseProblem(query.error as AxiosError).code : undefined

  // ---- save ---------------------------------------------------------------

  async function handleSave() {
    setConcurrency(null)
    const body: SdtmSpecification = {
      schema_version: '1.0.0',
      domains,
    }
    try {
      await put.mutateAsync({ sdtmId, data: body })
      toast.success('Specification saved.')
    } catch (error) {
      const err = error as AxiosError
      if (err.response?.status === 412) {
        // Concurrency conflict: show the message and require a reload of the
        // current Specification revision before the user can retry (11.7).
        setConcurrency(
          stalenessAlert(err) ??
            'This Specification changed since you opened it. Reload and try again.',
        )
        return
      }
      toast.error(
        parseProblem(err).detail ?? err.message ?? 'Could not save the Specification.',
      )
    }
  }

  async function reloadCurrentRevision() {
    setConcurrency(null)
    // Force the editor to re-seed from the freshly fetched revision.
    seededRevision.current = null
    await qc.invalidateQueries({ queryKey: specKey })
  }

  // ---- import -------------------------------------------------------------

  function handleImportFiles(files: File[]) {
    const file = files[0]
    if (!file) return
    setImportProblem(null)
    // One stable Idempotency-Key per import attempt, held across retries.
    const key = importKey.begin()
    const contentType = inferImportContentType(file)
    // The backend reads the raw request body and branches on content type
    // (JSON vs XLSX). Send the file bytes directly with the aggregate ETag and
    // the stable Idempotency-Key. Stashing the config in the ref and bumping
    // `pendingImport` re-renders the hook with this request before the effect
    // below fires the mutation.
    importRequestRef.current = {
      data: file,
      headers: {
        ...ifMatch().headers,
        'Content-Type': contentType,
        'Idempotency-Key': key,
      },
    }
    setPendingImport(file)
  }

  const runImport = React.useCallback(async () => {
    try {
      await importSpec.mutateAsync({ sdtmId })
      await invalidateSdtmSubResource(qc, 'specification', sdtmId)
      // Re-seed the editor from the imported revision.
      seededRevision.current = null
      await qc.invalidateQueries({ queryKey: specKey })
      toast.success('Specification imported.')
    } catch (error) {
      const err = error as AxiosError
      if (err.response?.status === 422) {
        // sdtm_specification_import_invalid: render detail + issues[] inline.
        setImportProblem(err)
        return
      }
      if (err.response?.status === 412) {
        setConcurrency(
          stalenessAlert(err) ??
            'This workbench changed since you opened it. Reload and try again.',
        )
        return
      }
      toast.error(
        parseProblem(err).detail ?? err.message ?? 'Could not import the Specification.',
      )
    } finally {
      importRequestRef.current = undefined
      setPendingImport(null)
    }
  }, [importSpec, sdtmId, qc, specKey])

  // Fire the import once a re-render has instantiated the mutation hook with
  // the pending request config captured by `handleImportFiles`.
  React.useEffect(() => {
    if (!pendingImport || !importRequestRef.current) return
    void runImport()
    // Only re-run when a new import is queued; `runImport` reads the latest ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingImport])

  // ---- export -------------------------------------------------------------

  async function handleExport(format: 'json' | 'xlsx') {
    try {
      await download.downloadSpecificationExport(sdtmId, format)
    } catch (error) {
      const err = error as AxiosError
      toast.error(
        parseProblem(err).detail ?? err.message ?? 'Could not export the Specification.',
      )
    }
  }

  // ---- render -------------------------------------------------------------

  if (query.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  // 404 sdtm_specification_required -> unsaved empty state (11.2). Still offer
  // an import dropzone so the user can author the first revision from a file.
  if (status === 404 && notFoundCode === 'sdtm_specification_required') {
    return (
      <div className="flex flex-col gap-4">
        <EmptyState
          title="No Specification yet"
          description="This SDTM workbench has no saved Specification. Save one below, or import a Specification file to create the first revision."
        />
        <ConcurrencyNotice message={concurrency} onReload={reloadCurrentRevision} />
        <IndustryStandardCard
          products={standardProducts.data ?? []}
          versions={eligibleSdtmVersions(standardVersions.data)}
          productId={standardProductId}
          versionId={standardVersionId}
          savedVersionId={selectedStandard?.standard_version_id}
          domainOptions={
            initializationOptionsMatch ? initializationOptions.data?.domains ?? [] : []
          }
          onProductChange={(value) => {
            setStandardProductId(value)
            setStandardVersionId('')
            setStandardSelectionProblem(null)
          }}
          onVersionChange={(value) => {
            setStandardVersionId(value)
            setStandardSelectionProblem(null)
          }}
          onSaveSelection={handleSaveStandardSelection}
          isCatalogLoading={standardProducts.isLoading || standardVersions.isLoading}
          isOptionsLoading={
            canLoadInitializationOptions &&
            (initializationOptions.isLoading ||
              initializationOptions.isFetching ||
              !initializationOptionsMatch)
          }
          catalogProblem={standardCatalogProblem}
          optionsProblem={initializationOptionsProblem}
          isSavingSelection={replaceDependencies.isPending}
          selectionProblem={standardSelectionProblem}
          onInitialize={handleInitialize}
          isPending={initialize.isPending}
          problem={initializeProblem}
        />
        <ImportCard
          onFiles={handleImportFiles}
          isPending={importSpec.isPending}
          problem={importProblem}
        />
        <SpecificationAuthoringCard
          domains={domains}
          onChange={setDomains}
          onSave={handleSave}
          isSaving={put.isPending}
        />
      </div>
    )
  }

  // Any other load error (not the "not yet authored" 404).
  if (query.isError) {
    return <ErrorState error={query.error} resourceLabel="SDTM Specification" />
  }

  if (!spec) {
    return (
      <EmptyState
        title="No Specification"
        description="The Specification is unavailable."
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Specification</CardTitle>
          <CardDescription>
            Revision {spec.revision} · schema version {spec.schema_version}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => handleExport('json')}
            disabled={download.isPending}
          >
            <Download /> Export JSON
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => handleExport('xlsx')}
            disabled={download.isPending}
          >
            <Download /> Export XLSX
          </Button>
        </CardContent>
      </Card>

      <ConcurrencyNotice message={concurrency} onReload={reloadCurrentRevision} />

      <IndustryStandardCard
        products={standardProducts.data ?? []}
        versions={eligibleSdtmVersions(standardVersions.data)}
        productId={standardProductId}
        versionId={standardVersionId}
        savedVersionId={selectedStandard?.standard_version_id}
        domainOptions={
          initializationOptionsMatch ? initializationOptions.data?.domains ?? [] : []
        }
        onProductChange={(value) => {
          setStandardProductId(value)
          setStandardVersionId('')
          setStandardSelectionProblem(null)
        }}
        onVersionChange={(value) => {
          setStandardVersionId(value)
          setStandardSelectionProblem(null)
        }}
        onSaveSelection={handleSaveStandardSelection}
        isCatalogLoading={standardProducts.isLoading || standardVersions.isLoading}
        isOptionsLoading={
          canLoadInitializationOptions &&
          (initializationOptions.isLoading ||
            initializationOptions.isFetching ||
            !initializationOptionsMatch)
        }
        catalogProblem={standardCatalogProblem}
        optionsProblem={initializationOptionsProblem}
        isSavingSelection={replaceDependencies.isPending}
        selectionProblem={standardSelectionProblem}
        onInitialize={handleInitialize}
        isPending={initialize.isPending}
        problem={initializeProblem}
      />

      <ImportCard
        onFiles={handleImportFiles}
        isPending={importSpec.isPending}
        problem={importProblem}
      />

      <SpecificationAuthoringCard
        domains={domains}
        onChange={setDomains}
        onSave={handleSave}
        isSaving={put.isPending}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface ConcurrencyNoticeProps {
  message: string | null
  onReload: () => void
}

/** Persistent 412 concurrency notice with a reload action (11.7). */
function ConcurrencyNotice({ message, onReload }: ConcurrencyNoticeProps) {
  if (!message) return null
  return (
    <div
      role="alert"
      className="border-destructive/50 text-destructive flex flex-col gap-2 rounded-md border px-4 py-3 text-sm"
    >
      <span className="font-medium">Specification changed</span>
      <span className="text-destructive/90">{message}</span>
      <button
        type="button"
        onClick={onReload}
        className="text-destructive w-fit text-sm font-medium underline underline-offset-2"
      >
        Reload current Specification revision
      </button>
    </div>
  )
}

interface ImportCardProps {
  onFiles: (files: File[]) => void
  isPending: boolean
  problem: AxiosError | null
}

interface IndustryStandardCardProps {
  products: Array<{ id: string; name: string; provider: string }>
  versions: StandardVersionResponse[]
  productId: string
  versionId: string
  savedVersionId: string | undefined
  domainOptions: SdtmStandardDomainOption[]
  onProductChange: (value: string) => void
  onVersionChange: (value: string) => void
  onSaveSelection: () => void
  isCatalogLoading: boolean
  isOptionsLoading: boolean
  catalogProblem: string | null
  optionsProblem: string | null
  isSavingSelection: boolean
  selectionProblem: string | null
  onInitialize: (command: SdtmSpecificationInitialize) => void
  isPending: boolean
  problem: string | null
}

/** Add missing factual structures from the exact selected SDTMIG dependency. */
function IndustryStandardCard({
  products,
  versions,
  productId,
  versionId,
  savedVersionId,
  domainOptions,
  onProductChange,
  onVersionChange,
  onSaveSelection,
  isCatalogLoading,
  isOptionsLoading,
  catalogProblem,
  optionsProblem,
  isSavingSelection,
  selectionProblem,
  onInitialize,
  isPending,
  problem,
}: IndustryStandardCardProps) {
  const [selectedDomainCodes, setSelectedDomainCodes] = React.useState<string[]>([])
  const [requiredExpectedOnly, setRequiredExpectedOnly] = React.useState(false)

  React.useEffect(() => {
    setSelectedDomainCodes([])
    setRequiredExpectedOnly(false)
  }, [savedVersionId])

  function toggleDomain(code: string, checked: boolean) {
    setSelectedDomainCodes((current) =>
      checked
        ? [...current, code]
        : current.filter((item) => item !== code),
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <LibraryBig className="size-4" aria-hidden /> Industry standard
        </CardTitle>
        <CardDescription>
          Add missing domains and variables from the exact SDTM implementation
          guide version selected below. Existing manual edits are preserved.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="sdtm-standard-product">Implementation guide</Label>
            <Select
              value={productId}
              onValueChange={onProductChange}
              disabled={isCatalogLoading || products.length === 0}
            >
              <SelectTrigger id="sdtm-standard-product" className="w-full">
                <SelectValue placeholder="Select an implementation guide" />
              </SelectTrigger>
              <SelectContent>
                {products.map((product) => (
                  <SelectItem key={product.id} value={product.id}>
                    {product.name} · {product.provider}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="sdtm-standard-version">Version</Label>
            <Select
              value={versionId}
              onValueChange={onVersionChange}
              disabled={!productId || isCatalogLoading || versions.length === 0}
            >
              <SelectTrigger id="sdtm-standard-version" className="w-full">
                <SelectValue placeholder="Select an exact version" />
              </SelectTrigger>
              <SelectContent>
                {versions.map((version) => (
                  <SelectItem key={version.id} value={version.id}>
                    {version.version} · {version.lifecycle}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        {!isCatalogLoading && !catalogProblem && products.length === 0 && (
          <p className="text-muted-foreground text-sm">
            No SDTM implementation guides are registered in the Standards catalog.
          </p>
        )}
        {!isCatalogLoading &&
          !catalogProblem &&
          productId &&
          versions.length === 0 && (
            <p className="text-muted-foreground text-sm">
              This implementation guide has no eligible SDTM versions.
            </p>
          )}
        {versionId && versionId !== savedVersionId && (
          <p className="text-muted-foreground text-sm">
            Save this exact version before populating the Specification.
          </p>
        )}
        {savedVersionId && versionId === savedVersionId && (
          <fieldset className="flex flex-col gap-3 rounded-md border p-3">
            <legend className="px-1 text-sm font-medium">Domains to populate</legend>
            {isOptionsLoading ? (
              <p className="text-muted-foreground flex items-center gap-2 text-sm">
                <Loader2 className="size-4 animate-spin" /> Loading standard domains…
              </p>
            ) : domainOptions.length === 0 && !optionsProblem ? (
              <p className="text-muted-foreground text-sm">
                No concrete domains are available from this standard version.
              </p>
            ) : (
              <>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      setSelectedDomainCodes(domainOptions.map((item) => item.code))
                    }
                    disabled={domainOptions.length === 0}
                  >
                    Select all
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelectedDomainCodes([])}
                    disabled={selectedDomainCodes.length === 0}
                  >
                    Clear
                  </Button>
                </div>
                <div className="grid max-h-64 gap-2 overflow-y-auto sm:grid-cols-2">
                  {domainOptions.map((domain) => (
                    <label
                      key={domain.code}
                      className="hover:bg-muted/50 flex cursor-pointer gap-2 rounded-md border p-2 text-sm"
                    >
                      <input
                        type="checkbox"
                        aria-label={`Select ${domain.code} — ${domain.label}`}
                        checked={selectedDomainCodes.includes(domain.code)}
                        onChange={(event) =>
                          toggleDomain(domain.code, event.target.checked)
                        }
                      />
                      <span>
                        <span className="font-medium">
                          {domain.code} — {domain.label}
                        </span>
                        <span className="text-muted-foreground block text-xs">
                          {domain.domain_class} · {domain.required_variable_count} Req ·{' '}
                          {domain.expected_variable_count} Exp ·{' '}
                          {domain.permissible_variable_count} Perm
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
                <label className="flex items-center gap-2 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={requiredExpectedOnly}
                    onChange={(event) => setRequiredExpectedOnly(event.target.checked)}
                  />
                  Include only Required and Expected variables
                </label>
                <p className="text-muted-foreground text-xs">
                  This filter controls new additions only. Existing variables are never removed.
                </p>
              </>
            )}
          </fieldset>
        )}
        {catalogProblem && (
          <p className="text-destructive text-sm font-medium" role="alert">
            {catalogProblem}
          </p>
        )}
        {optionsProblem && (
          <p className="text-destructive text-sm font-medium" role="alert">
            {optionsProblem}
          </p>
        )}
        {selectionProblem && (
          <p className="text-destructive text-sm font-medium" role="alert">
            {selectionProblem}
          </p>
        )}
        {problem && (
          <p className="text-destructive text-sm font-medium" role="alert">
            {problem}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={onSaveSelection}
            disabled={
              !versionId ||
              versionId === savedVersionId ||
              isSavingSelection ||
              isPending
            }
          >
            {isSavingSelection ? <Loader2 className="animate-spin" /> : <Save />}
            {isSavingSelection ? 'Saving selection…' : 'Save standard selection'}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() =>
              onInitialize({
                domain_codes: selectedDomainCodes,
                required_expected_only: requiredExpectedOnly,
              })
            }
            disabled={
              !savedVersionId ||
              versionId !== savedVersionId ||
              selectedDomainCodes.length === 0 ||
              isOptionsLoading ||
              !!optionsProblem ||
              isPending
            }
          >
            {isPending ? <Loader2 className="animate-spin" /> : <LibraryBig />}
            {isPending ? 'Populating…' : 'Populate from industry standard'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

/** Import a Specification file; renders a 422 import-invalid detail + issues. */
function ImportCard({ onFiles, isPending, problem }: ImportCardProps) {
  const parsed = problem ? parseProblem(problem) : null
  const issues = (parsed?.issues ?? []) as Record<string, unknown>[]
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Upload className="size-4" aria-hidden /> Import
        </CardTitle>
        <CardDescription>
          Replace the Specification from a JSON or XLSX file. The import is
          atomic and uses the current workbench revision.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FileDropzone
          onFiles={onFiles}
          disabled={isPending}
          accept=".json,.xlsx,application/json,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          ariaLabel="Specification import drop target"
          label="Drag a Specification file here, or browse"
          description="Accepted formats: JSON (.json) or Excel (.xlsx)"
        />
        {parsed && (
          <div className="flex flex-col gap-2">
            <p className="text-destructive text-sm font-medium" role="alert">
              {parsed.detail ?? 'The Specification import is invalid.'}
            </p>
            {issues.length > 0 && (
              <IssueList
                issues={issues}
                emptyTitle="No import issues"
                emptyDescription="The import reported no field-level issues."
              />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Read the domains out of the opaque Specification payload. The generated
 * payload is `{ [key: string]: unknown }`, so the panel reads the `domains`
 * array defensively and keeps the typed {@link SdtmDomain} shape it edits.
 */
function domainsFromPayload(
  payload: SpecificationResponse['payload'],
): SdtmDomain[] {
  const raw = (payload as { domains?: unknown }).domains
  if (!Array.isArray(raw)) return []
  return raw as SdtmDomain[]
}

/** Keep only exact SDTMIG releases that can satisfy the SDTM dependency slot. */
function eligibleSdtmVersions(
  versions: StandardVersionResponse[] | undefined,
): StandardVersionResponse[] {
  return (versions ?? []).filter(
    (version) =>
      version.applicable_modules.includes('sdtm') &&
      (version.purposes.includes('sdtm_ig') ||
        version.purposes.includes('reference_metadata')),
  )
}

/**
 * Decide the request content type from the file so the backend branches to the
 * JSON or XLSX parser. JSON files are sent as `application/json`; everything
 * else is sent as the XLSX media type.
 */
function inferImportContentType(file: File): string {
  const name = file.name.toLowerCase()
  if (name.endsWith('.json') || file.type === 'application/json') {
    return 'application/json'
  }
  return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
}

export default SpecificationPanel
