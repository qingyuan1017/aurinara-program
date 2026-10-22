import { getAuthToken } from "@/lib/auth";

export type RepositoryCapabilities = {
  can_preview: boolean;
  can_edit: boolean;
  can_annotate: boolean;
  can_manage: boolean;
  conversion_targets: Array<"csv" | "parquet">;
};
export type RepositoryVersion = {
  id: string;
  node_id: string;
  version_number: number;
  sha256: string;
  size_bytes: number;
  media_type: string;
  created_at: string;
  profile: {
    file_kind: string;
    processing_status: string;
    failure_code: string | null;
    metadata_json: Record<string, unknown>;
  } | null;
  capabilities: RepositoryCapabilities;
};
export type RepositoryNode = {
  id: string;
  study_id: string;
  parent_id: string | null;
  kind: "folder" | "file";
  display_name: string;
  source_product: string;
  module: string | null;
  source_status: string;
  classification: string;
  lifecycle_status: "active" | "archived";
  revision: number;
  current_version_number: number | null;
  required_read_action: string;
  required_write_action: string;
  site_id: string | null;
  updated_at: string;
  current_version: RepositoryVersion | null;
  capabilities: RepositoryCapabilities;
};
export type RepositoryPage = {
  items: RepositoryNode[];
  next_cursor: string | null;
  capabilities: { can_upload: boolean; can_create_folder: boolean };
};
export type TabularPreview = {
  processing_status: string;
  schema: Array<{ name: string; type: string }>;
  rows: Array<Record<string, unknown>>;
  total_rows: number;
  page: number;
  page_size: number;
  parsing: Record<string, unknown>;
};
export type PdfAnnotation = {
  id: string;
  version_id: string;
  page_number: number;
  geometry: { x: number; y: number; width: number; height: number };
  comment: string | null;
  category: string;
  status: string;
  revision: number;
};
export type RepositoryJob = {
  id: string;
  state: "queued" | "running" | "succeeded" | "failed";
  failure_code: string | null;
  result: Record<string, unknown>;
};

const base = (import.meta.env.VITE_PLATFORM_API_BASE_URL ?? "").replace(
  /\/$/,
  "",
);

export async function repositoryRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${getAuthToken()}`,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    throw new Error(
      problem?.error?.message ||
        `Repository request failed (${response.status})`,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const repositoryApi = {
  browse: (studyId: string, params: URLSearchParams) =>
    repositoryRequest<RepositoryPage>(
      `/v1/studies/${studyId}/repository?${params}`,
    ),
  versions: (nodeId: string) =>
    repositoryRequest<RepositoryVersion[]>(
      `/v1/repository/nodes/${nodeId}/versions`,
    ),
  version: (versionId: string) =>
    repositoryRequest<RepositoryVersion & { study_id: string }>(
      `/v1/repository/versions/${versionId}`,
    ),
  node: (nodeId: string) =>
    repositoryRequest<RepositoryNode>(`/v1/repository/nodes/${nodeId}`),
  download: (versionId: string) =>
    repositoryRequest<{ url: string }>(
      `/v1/repository/versions/${versionId}/download`,
      { method: "POST" },
    ),
  folder: (studyId: string, name: string, parentId: string | null) =>
    repositoryRequest<RepositoryNode>(
      `/v1/studies/${studyId}/repository/folders`,
      { method: "POST", body: JSON.stringify({ name, parent_id: parentId }) },
    ),
  patch: (node: RepositoryNode, body: object) =>
    repositoryRequest<RepositoryNode>(`/v1/repository/nodes/${node.id}`, {
      method: "PATCH",
      headers: { "If-Match": `"${node.revision}"` },
      body: JSON.stringify(body),
    }),
  archive: (node: RepositoryNode) =>
    repositoryRequest<RepositoryNode>(`/v1/repository/nodes/${node.id}`, {
      method: "DELETE",
      headers: { "If-Match": `"${node.revision}"` },
    }),
  restore: (node: RepositoryNode) =>
    repositoryRequest<RepositoryNode>(
      `/v1/repository/nodes/${node.id}/restore`,
      { method: "POST", headers: { "If-Match": `"${node.revision}"` } },
    ),
  preview: (versionId: string, body: object) =>
    repositoryRequest<TabularPreview>(
      `/v1/repository/versions/${versionId}/tabular-preview`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  annotations: (versionId: string) =>
    repositoryRequest<PdfAnnotation[]>(
      `/v1/repository/versions/${versionId}/annotations`,
    ),
  annotate: (versionId: string, body: object) =>
    repositoryRequest<PdfAnnotation>(
      `/v1/repository/versions/${versionId}/annotations`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  deleteAnnotation: (value: PdfAnnotation) =>
    repositoryRequest<void>(`/v1/repository/annotations/${value.id}`, {
      method: "DELETE",
      headers: { "If-Match": `"${value.revision}"` },
    }),
  convert: (versionId: string, target: "csv" | "parquet", filename: string) =>
    repositoryRequest<RepositoryJob>(
      `/v1/repository/versions/${versionId}/conversions`,
      {
        method: "POST",
        body: JSON.stringify({
          target,
          filename,
          idempotency_key: crypto.randomUUID(),
        }),
      },
    ),
  exportPdf: (versionId: string, filename: string) =>
    repositoryRequest<RepositoryJob>(
      `/v1/repository/versions/${versionId}/annotated-exports`,
      {
        method: "POST",
        body: JSON.stringify({
          filename,
          idempotency_key: crypto.randomUUID(),
        }),
      },
    ),
  office: (versionId: string, mode: "view" | "edit") =>
    repositoryRequest<{
      document_server_url: string;
      config: Record<string, unknown>;
    }>(`/v1/repository/versions/${versionId}/office-sessions`, {
      method: "POST",
      body: JSON.stringify({ mode }),
    }),
  job: (jobId: string) =>
    repositoryRequest<RepositoryJob>(`/v1/repository/jobs/${jobId}`),
};

export async function waitForRepositoryJob(
  initial: RepositoryJob,
  timeoutMs = 120_000,
): Promise<RepositoryJob> {
  const deadline = Date.now() + timeoutMs;
  let job = initial;
  while (job.state === "queued" || job.state === "running") {
    if (Date.now() >= deadline) throw new Error("Repository job timed out");
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
    job = await repositoryApi.job(job.id);
  }
  if (job.state === "failed") {
    throw new Error(`Repository job failed (${job.failure_code || "unknown"})`);
  }
  return job;
}

export type UploadProgress = {
  phase: "hashing" | "uploading" | "completing";
  loaded: number;
  total: number;
};
async function hash(
  file: File,
  progress: (value: UploadProgress) => void,
  signal: AbortSignal,
) {
  return new Promise<string>((resolve, reject) => {
    const worker = new Worker(
      new URL("../repositoryHash.worker.ts", import.meta.url),
      { type: "module" },
    );
    const abort = () => {
      worker.terminate();
      reject(new DOMException("Upload cancelled", "AbortError"));
    };
    signal.addEventListener("abort", abort, { once: true });
    worker.onmessage = (
      event: MessageEvent<{
        type: string;
        loaded?: number;
        total?: number;
        sha256?: string;
      }>,
    ) => {
      if (event.data.type === "progress")
        progress({
          phase: "hashing",
          loaded: event.data.loaded || 0,
          total: event.data.total || file.size,
        });
      if (event.data.sha256) {
        worker.terminate();
        resolve(event.data.sha256);
      }
    };
    worker.onerror = reject;
    worker.postMessage(file);
  });
}
async function put(url: string, data: Blob, signal: AbortSignal) {
  let failure: unknown;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(url, { method: "PUT", body: data, signal });
      if (!response.ok) throw new Error(`Part failed (${response.status})`);
      return response.headers.get("ETag") || "uploaded";
    } catch (error) {
      failure = error;
      if (signal.aborted) throw error;
    }
  }
  throw failure;
}
export async function uploadRepositoryFile(
  studyId: string,
  file: File,
  parentId: string | null,
  replacement: RepositoryNode | null,
  progress: (value: UploadProgress) => void,
  signal: AbortSignal,
) {
  const sha256 = await hash(file, progress, signal);
  const partSize = 16 * 1024 * 1024;
  const session = await repositoryRequest<{
    object_id: string;
    parts: Array<{ part_number: number; url: string }>;
  }>(`/v1/studies/${studyId}/repository/uploads`, {
    method: "POST",
    body: JSON.stringify({
      filename: file.name,
      size_bytes: file.size,
      sha256,
      media_type: file.type || "application/octet-stream",
      part_count: Math.max(1, Math.ceil(file.size / partSize)),
      parent_id: replacement ? null : parentId,
      replacement_node_id: replacement?.id || null,
      classification: replacement?.classification || "internal",
      idempotency_key: crypto.randomUUID(),
    }),
  });
  try {
    let loaded = 0;
    const results = new Map<number, string>();
    const queue = [...session.parts];
    await Promise.all(
      Array.from({ length: Math.min(3, queue.length) }, async () => {
        while (queue.length) {
          const part = queue.shift();
          if (!part) return;
          const start = (part.part_number - 1) * partSize;
          const blob = file.slice(start, start + partSize);
          results.set(part.part_number, await put(part.url, blob, signal));
          loaded += blob.size;
          progress({ phase: "uploading", loaded, total: file.size });
        }
      }),
    );
    progress({ phase: "completing", loaded: file.size, total: file.size });
    return repositoryRequest<RepositoryNode>(
      `/v1/repository/uploads/${session.object_id}/complete`,
      {
        method: "POST",
        body: JSON.stringify({
          parts: [...results]
            .sort(([a], [b]) => a - b)
            .map(([part_number, etag]) => ({ part_number, etag })),
        }),
      },
    );
  } catch (error) {
    await repositoryRequest(`/v1/repository/uploads/${session.object_id}`, {
      method: "DELETE",
    }).catch(() => undefined);
    throw error;
  }
}
