import {
  type ChangeEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createFileRoute } from "@tanstack/react-router";
import {
  Archive,
  Database,
  Download,
  Eye,
  File,
  FileSpreadsheet,
  FileText,
  Folder,
  FolderPlus,
  Presentation,
  RefreshCw,
  Search,
  Share2,
  Table2,
  Upload,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { RepositoryPreview } from "@/components/repository-preview";
import { useCurrentStudy } from "@/components/study-context";
import { AXIOS_INSTANCE } from "@/api/axios-instance";
import {
  repositoryApi,
  uploadRepositoryFile,
  waitForRepositoryJob,
  type RepositoryNode,
  type RepositoryVersion,
  type UploadProgress,
} from "@/lib/repository-client";

export const Route = createFileRoute("/_app/repository")({
  component: RepositoryPage,
});

const extensionKinds: Record<string, string> = {
  pdf: "pdf", docx: "docx", xlsx: "xlsx", pptx: "pptx", csv: "csv", parquet: "parquet",
};

function repositoryFileKind(node: RepositoryNode): string {
  if (node.kind === "folder") return "folder";
  const detected = node.current_version?.profile?.file_kind;
  if (detected && detected !== "unknown") return detected;
  return extensionKinds[node.display_name.split(".").pop()?.toLowerCase() || ""] || "file";
}

function RepositoryEntryIcon({ node, className = "size-4" }: { node: RepositoryNode; className?: string }) {
  const kind = repositoryFileKind(node);
  const colors: Record<string, string> = { folder: "text-amber-600", pdf: "text-red-600", docx: "text-blue-600", xlsx: "text-emerald-600", pptx: "text-orange-600", csv: "text-teal-600", parquet: "text-violet-600", file: "text-muted-foreground" };
  const props = { className: `${className} shrink-0 ${colors[kind] || colors.file}`, "aria-label": kind === "folder" ? "Folder" : `${kind.toUpperCase()} file` };
  if (kind === "folder") return <Folder {...props} />;
  if (kind === "pdf" || kind === "docx") return <FileText {...props} />;
  if (kind === "xlsx") return <FileSpreadsheet {...props} />;
  if (kind === "pptx") return <Presentation {...props} />;
  if (kind === "csv") return <Table2 {...props} />;
  if (kind === "parquet") return <Database {...props} />;
  return <File {...props} />;
}

function RepositoryPage() {
  const { currentStudyId } = useCurrentStudy();
  const [query, setQuery] = useState("");
  const [view, setView] = useState("folder");
  const [path, setPath] = useState<RepositoryNode[]>([]);
  const [items, setItems] = useState<RepositoryNode[]>([]);
  const [folders, setFolders] = useState<RepositoryNode[]>([]);
  const [selected, setSelected] = useState<RepositoryNode | null>(null);
  const [versions, setVersions] = useState<RepositoryVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState(false);
  const [caps, setCaps] = useState({
    can_upload: false,
    can_create_folder: false,
  });
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController>();
  const deepNodeId = useRef<string | null>(null);
  const currentFolder = path.at(-1) ?? null;

  useEffect(() => {
    if (!preview) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreview(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [preview]);

  const load = useCallback(async () => {
    if (!currentStudyId) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ view, limit: "100" });
      if (view === "folder" && currentFolder)
        params.set("parent_id", currentFolder.id);
      if (query.trim()) params.set("q", query.trim());
      const [page, all] = await Promise.all([
        repositoryApi.browse(currentStudyId, params),
        repositoryApi.browse(
          currentStudyId,
          new URLSearchParams({ view: "all", limit: "100" }),
        ),
      ]);
      setItems(page.items);
      setCaps(page.capabilities);
      setFolders(
        all.items.filter(
          (item) =>
            item.kind === "folder" && item.lifecycle_status === "active",
        ),
      );
      setSelected(
        (value) =>
          page.items.find((item) => item.id === value?.id) ??
          (value?.id === deepNodeId.current ? value : null),
      );
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Repository unavailable",
      );
    } finally {
      setLoading(false);
    }
  }, [currentStudyId, currentFolder, query, view]);

  useEffect(() => {
    setPath([]);
    setSelected(null);
  }, [currentStudyId]);
  useEffect(() => {
    const parameters = new URLSearchParams(location.search);
    const linkedVersion = parameters.get("version");
    const linkedStudy = parameters.get("study");
    if (!linkedVersion || !currentStudyId) return;
    setView("all");
    void repositoryApi
      .version(linkedVersion)
      .then(async (binding) => {
        if (
          binding.study_id !== currentStudyId ||
          (linkedStudy && linkedStudy !== currentStudyId)
        )
          throw new Error("The deep link belongs to another study");
        deepNodeId.current = binding.node_id;
        setSelected(await repositoryApi.node(binding.node_id));
        setPreview(true);
      })
      .catch((error) =>
        toast.error(
          error instanceof Error ? error.message : "Deep link unavailable",
        ),
      );
  }, [currentStudyId]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (!selected || selected.kind !== "file") {
      setVersions([]);
      return;
    }
    void repositoryApi
      .versions(selected.id)
      .then((values) => {
        setVersions(values);
        const linked = new URLSearchParams(location.search).get("version");
        if (linked && !values.some((value) => value.id === linked))
          toast.error(
            "The linked Repository version is unavailable or unauthorized",
          );
      })
      .catch((error) =>
        toast.error(
          error instanceof Error ? error.message : "Version unavailable",
        ),
      );
  }, [selected]);

  const destinations = useMemo(
    () =>
      folders.filter(
        (folder) =>
          selected &&
          folder.id !== selected.id &&
          folder.source_product === selected.source_product &&
          folder.required_read_action === selected.required_read_action &&
          folder.required_write_action === selected.required_write_action &&
          folder.site_id === selected.site_id,
      ),
    [folders, selected],
  );
  const download = async (version = versions[0]) => {
    if (!version) return;
    const result = await repositoryApi.download(version.id);
    window.open(result.url, "_blank", "noopener,noreferrer");
  };
  const addToAurinara = async () => {
    if (!currentStudyId || !versions[0]) return;
    try {
      await AXIOS_INSTANCE.post(
        `/api/v1/studies/${currentStudyId}/source-files:bind-repository`,
        { version_id: versions[0].id, expected_sha256: versions[0].sha256 },
      );
      toast.success("Repository version added as a new Aurinara source file");
    } catch {
      toast.error("Could not bind this Repository version");
    }
  };
  const createFolder = async () => {
    const name = prompt("Folder name")?.trim();
    if (!name || !currentStudyId) return;
    try {
      await repositoryApi.folder(
        currentStudyId,
        name,
        currentFolder?.id || null,
      );
      await load();
    } catch (error) {
      toast.error(String(error));
    }
  };
  const changeName = async () => {
    if (!selected) return;
    const name = prompt("New name", selected.display_name)?.trim();
    if (!name) return;
    try {
      setSelected(await repositoryApi.patch(selected, { name }));
      await load();
    } catch (error) {
      toast.error(String(error));
    }
  };
  const move = async (parentId: string) => {
    if (!selected) return;
    try {
      setSelected(
        await repositoryApi.patch(selected, { parent_id: parentId || null }),
      );
      await load();
    } catch (error) {
      toast.error(String(error));
    }
  };
  const archive = async () => {
    if (!selected) return;
    try {
      setSelected(
        selected.lifecycle_status === "archived"
          ? await repositoryApi.restore(selected)
          : await repositoryApi.archive(selected),
      );
      await load();
    } catch (error) {
      toast.error(String(error));
    }
  };
  const upload = async (
    event: ChangeEvent<HTMLInputElement>,
    replacement: RepositoryNode | null = null,
  ) => {
    const file = event.target.files?.[0];
    if (!file || !currentStudyId) return;
    abort.current = new AbortController();
    try {
      await uploadRepositoryFile(
        currentStudyId,
        file,
        currentFolder?.id || null,
        replacement,
        setProgress,
        abort.current.signal,
      );
      toast.success(
        replacement ? "New immutable version added" : "File uploaded",
      );
      await load();
      if (replacement)
        setVersions(await repositoryApi.versions(replacement.id));
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError"))
        toast.error(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setProgress(null);
      event.target.value = "";
    }
  };
  const convert = async (target: "csv" | "parquet") => {
    if (!selected || !versions[0]) return;
    const filename = prompt(
      "Output filename",
      `${selected.display_name.replace(/\.[^.]+$/, "")}.${target}`,
    )?.trim();
    if (!filename) return;
    try {
      const job = await repositoryApi.convert(versions[0].id, target, filename);
      toast.info("Conversion queued");
      await waitForRepositoryJob(job);
      toast.success("Conversion completed");
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Conversion failed");
    }
  };
  if (!currentStudyId)
    return (
      <p className="text-sm text-muted-foreground">
        Select a study to use Repository.
      </p>
    );

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-display text-2xl font-medium">Repository</h1>
        <p className="text-muted-foreground text-sm">
          One authorized file experience across Platform, Aurinara, and EDC.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <div className="relative min-w-64 flex-1">
          <Search className="text-muted-foreground absolute top-2.5 left-3 size-4" />
          <input
            className="border-input bg-background h-9 w-full rounded-md border pl-9 text-sm"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search files"
          />
        </div>
        <select
          className="border-input bg-background h-9 rounded-md border px-3 text-sm"
          value={view}
          onChange={(event) => {
            setView(event.target.value);
            setSelected(null);
          }}
        >
          <option value="folder">Folders</option>
          <option value="all">All files</option>
          <option value="recent">Recent</option>
          <option value="aurinara">Aurinara</option>
          <option value="aurinara-edc">EDC</option>
          <option value="platform">Neutral</option>
          <option value="archived">Archived</option>
        </select>
        <Button
          variant="outline"
          disabled={!caps.can_create_folder}
          onClick={() => void createFolder()}
        >
          <FolderPlus />
          Folder
        </Button>
        <Button
          disabled={!caps.can_upload}
          onClick={() => input.current?.click()}
        >
          <Upload />
          Upload
        </Button>
        <input
          ref={input}
          hidden
          type="file"
          onChange={(event) => void upload(event)}
        />
        <Button variant="outline" size="icon" onClick={() => void load()}>
          <RefreshCw className={loading ? "animate-spin" : ""} />
        </Button>
        {progress && (
          <span className="self-center text-xs">
            {progress.phase}{" "}
            {Math.round((progress.loaded / Math.max(1, progress.total)) * 100)}%{" "}
            <button
              className="underline"
              onClick={() => abort.current?.abort()}
            >
              Cancel
            </button>
          </span>
        )}
      </div>
      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <Card className="gap-0 py-0">
          <div className="flex items-center gap-1 border-b px-4 py-3 text-sm">
            <button
              className="text-primary"
              onClick={() => {
                setPath([]);
                setView("folder");
              }}
            >
              Repository
            </button>
            {path.map((folder, index) => (
              <span key={folder.id}>
                {" "}
                /{" "}
                <button
                  className="text-primary"
                  onClick={() => setPath(path.slice(0, index + 1))}
                >
                  {folder.display_name}
                </button>
              </span>
            ))}
          </div>
          {items.map((item) => (
            <button
              key={item.id}
              className={`grid w-full grid-cols-[1fr_110px_100px] items-center border-b px-4 py-3 text-left text-sm hover:bg-muted/50 ${selected?.id === item.id ? "bg-muted" : ""}`}
              onClick={() => setSelected(item)}
              onDoubleClick={() =>
                item.kind === "folder" &&
                (setPath([...path, item]), setView("folder"), setSelected(null))
              }
            >
              <span className="flex min-w-0 items-center gap-2">
                <RepositoryEntryIcon node={item} />
                <span className="truncate">{item.display_name}</span>
              </span>
              <span className="truncate text-xs text-muted-foreground">
                {item.source_product}
              </span>
              <span className="text-xs text-muted-foreground">
                {item.lifecycle_status === "archived"
                  ? "archived"
                  : item.source_status}
              </span>
            </button>
          ))}
          {!loading && !items.length && (
            <p className="p-12 text-center text-sm text-muted-foreground">
              No authorized entries found.
            </p>
          )}
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">{selected && <RepositoryEntryIcon node={selected} />}{selected?.display_name ?? "File details"}</CardTitle>
            <CardDescription>
              {selected
                ? `${selected.source_product} · ${selected.classification}`
                : "Select a file"}
            </CardDescription>
          </CardHeader>
          {selected && (
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {selected.capabilities.can_manage && (
                  <Button variant="outline" onClick={() => void changeName()}>
                    Rename
                  </Button>
                )}
                {selected.kind === "file" && (
                  <Button variant="outline" onClick={() => void download()}>
                    <Download />
                    Download
                  </Button>
                )}
                {selected.capabilities.can_preview && (
                  <Button
                    variant="outline"
                    onClick={() => setPreview(true)}
                  >
                    <Eye />
                    Open preview
                  </Button>
                )}
                {selected.kind === "file" && (
                  <Button onClick={() => void addToAurinara()}>
                    <Share2 />
                    Use in Aurinara
                  </Button>
                )}
                {selected.capabilities.can_manage && (
                  <Button variant="outline" onClick={() => void archive()}>
                    <Archive />
                    {selected.lifecycle_status === "archived"
                      ? "Restore"
                      : "Archive"}
                  </Button>
                )}
              </div>
              {selected.capabilities.can_manage && (
                <select
                  className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                  value={selected.parent_id || ""}
                  onChange={(event) => void move(event.target.value)}
                >
                  <option value="">Repository root</option>
                  {destinations.map((folder) => (
                    <option key={folder.id} value={folder.id}>
                      {folder.display_name}
                    </option>
                  ))}
                </select>
              )}
              {selected.kind === "file" && selected.capabilities.can_manage && (
                <label className="block cursor-pointer rounded-md border p-2 text-center text-sm">
                  <Upload className="mr-2 inline size-4" />
                  New version
                  <input
                    hidden
                    type="file"
                    onChange={(event) => void upload(event, selected)}
                  />
                </label>
              )}
              {versions[0]?.capabilities.conversion_targets.map((target) => (
                <Button
                  key={target}
                  variant="outline"
                  onClick={() => void convert(target)}
                >
                  Convert to {target.toUpperCase()}
                </Button>
              ))}
              <div className="space-y-2">
                {versions.map((version) => (
                  <button
                    key={version.id}
                    className="block w-full rounded-md bg-muted p-3 text-left text-xs"
                    onClick={() => void download(version)}
                  >
                    <strong>v{version.version_number}</strong>
                    <div className="text-muted-foreground">
                      {version.profile?.file_kind || version.media_type} ·{" "}
                      {version.profile?.processing_status || "pending"} ·{" "}
                      {(version.size_bytes / 1024).toFixed(1)} KB
                    </div>
                  </button>
                ))}
              </div>
            </CardContent>
          )}
        </Card>
      </div>
      {preview && selected?.kind === "file" && versions[0] && (
        <div
          className="fixed inset-0 z-[100] grid place-items-center bg-slate-950/75 p-3 backdrop-blur-sm md:p-8"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setPreview(false);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-label={`Preview ${selected.display_name}`}
            className="grid h-full w-full max-w-[1600px] grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-2xl border bg-background shadow-2xl"
          >
            <header className="flex items-center justify-between gap-4 border-b bg-card px-4 py-3 md:px-6">
              <div className="flex min-w-0 items-center gap-3">
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                  <RepositoryEntryIcon node={selected} className="size-5" />
                </span>
                <div className="min-w-0">
                  <p className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
                    {versions[0].profile?.file_kind || "file"} · Version {versions[0].version_number}
                  </p>
                  <h2 className="truncate text-base font-semibold md:text-lg">
                    {selected.display_name}
                  </h2>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span className="hidden rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-700 sm:inline">
                  {versions[0].profile?.processing_status || "pending"}
                </span>
                <Button variant="outline" onClick={() => void download(versions[0])}>
                  <Download />
                  <span className="hidden sm:inline">Download</span>
                </Button>
                <Button variant="outline" size="icon" aria-label="Close preview" onClick={() => setPreview(false)}>
                  <X />
                </Button>
              </div>
            </header>
            <div className="min-h-0 overflow-auto bg-muted/30 p-3 md:p-5">
              <RepositoryPreview
                node={selected}
                version={versions[0]}
                changed={() => void load()}
              />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
