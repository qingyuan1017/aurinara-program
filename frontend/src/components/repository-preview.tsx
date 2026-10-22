import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import {
  repositoryApi,
  waitForRepositoryJob,
  type PdfAnnotation,
  type RepositoryNode,
  type RepositoryVersion,
  type TabularPreview,
} from "@/lib/repository-client";

declare global {
  interface Window {
    DocsAPI?: {
      DocEditor: new (
        id: string,
        options: Record<string, unknown>,
      ) => { destroyEditor: () => void };
    };
  }
}

export function RepositoryPreview({
  node,
  version,
  changed,
}: {
  node: RepositoryNode;
  version: RepositoryVersion;
  changed: () => void;
}) {
  const kind = version.profile?.file_kind;
  if (version.profile?.processing_status === "pending")
    return <State text="Preparing preview…" />;
  if (version.profile?.processing_status === "failed")
    return (
      <State
        text={`Preview failed (${version.profile.failure_code}). The original remains downloadable.`}
      />
    );
  if (kind === "pdf")
    return <PdfPreview node={node} version={version} changed={changed} />;
  if (kind === "csv" || kind === "parquet")
    return <TablePreview version={version} />;
  if (["docx", "xlsx", "pptx"].includes(kind || ""))
    return <OfficePreview version={version} />;
  return <State text="No specialized preview is available." />;
}

function State({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
      {text}
    </div>
  );
}

function PdfPreview({
  node,
  version,
  changed,
}: {
  node: RepositoryNode;
  version: RepositoryVersion;
  changed: () => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy>();
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [annotations, setAnnotations] = useState<PdfAnnotation[]>([]);
  const [message, setMessage] = useState("");
  useEffect(() => {
    let active = true;
    let loadedPdf: PDFDocumentProxy | undefined;
    void (async () => {
      try {
        const [{ url }, pdfjs, worker] = await Promise.all([
          repositoryApi.download(version.id),
          import("pdfjs-dist"),
          import("pdfjs-dist/build/pdf.worker.min.mjs?url"),
        ]);
        pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
        const value = await pdfjs.getDocument({ url, disableRange: false })
          .promise;
        loadedPdf = value;
        if (active) setPdf(value);
      } catch (error) {
        setMessage(
          error instanceof Error ? error.message : "PDF preview failed",
        );
      }
    })();
    return () => {
      active = false;
      void loadedPdf?.cleanup();
    };
  }, [version.id]);
  useEffect(() => {
    if (!pdf || !canvas.current) return;
    void pdf.getPage(page).then(async (value) => {
      if (!canvas.current) return;
      const viewport = value.getViewport({ scale: 1.25 });
      canvas.current.width = viewport.width;
      canvas.current.height = viewport.height;
      const context = canvas.current.getContext("2d");
      if (context)
        await value.render({
          canvas: canvas.current,
          canvasContext: context,
          viewport,
        }).promise;
    });
  }, [pdf, page]);
  useEffect(() => {
    void repositoryApi
      .annotations(version.id)
      .then((values) => {
        setAnnotations(values);
        const linked = new URLSearchParams(location.search).get("annotation");
        const target = values.find((item) => item.id === linked);
        if (target) setPage(target.page_number);
      })
      .catch(() => setAnnotations([]));
  }, [version.id]);
  const search = async () => {
    if (!pdf || !query.trim()) return;
    let count = 0;
    for (let index = 1; index <= pdf.numPages; index += 1) {
      const content = await (await pdf.getPage(index)).getTextContent();
      const text = content.items
        .map((item) => ("str" in item ? item.str : ""))
        .join(" ")
        .toLowerCase();
      if (text.includes(query.toLowerCase())) {
        count += 1;
        if (count === 1) setPage(index);
      }
    }
    setMessage(`${count} matching pages`);
  };
  const annotate = async () => {
    const comment = prompt("Shared annotation comment")?.trim();
    if (!comment) return;
    const value = await repositoryApi.annotate(version.id, {
      page_number: page,
      geometry: { x: 0.08, y: 0.08, width: 0.35, height: 0.06 },
      comment,
    });
    setAnnotations((items) => [...items, value]);
  };
  const copyLink = (item: PdfAnnotation) =>
    navigator.clipboard.writeText(
      `${location.origin}${location.pathname}?study=${node.study_id}&version=${version.id}&annotation=${item.id}`,
    );
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button
          className="rounded border px-2 py-1"
          disabled={page <= 1}
          onClick={() => setPage((value) => value - 1)}
        >
          Previous
        </button>
        <span>
          {page} / {pdf?.numPages || "…"}
        </span>
        <button
          className="rounded border px-2 py-1"
          disabled={!pdf || page >= pdf.numPages}
          onClick={() => setPage((value) => value + 1)}
        >
          Next
        </button>
        <input
          className="h-8 rounded border px-2"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search text"
        />
        <button
          className="rounded border px-2 py-1"
          onClick={() => void search()}
        >
          Search
        </button>
        {version.capabilities.can_annotate && (
          <>
            <button
              className="rounded border px-2 py-1"
              onClick={() => void annotate()}
            >
              Annotate
            </button>
            <button
              className="rounded border px-2 py-1"
              onClick={() =>
                void repositoryApi
                  .exportPdf(
                    version.id,
                    node.display_name.replace(/\.pdf$/i, "") + "-annotated.pdf",
                  )
                  .then(waitForRepositoryJob)
                  .then(changed)
              }
            >
              Export
            </button>
          </>
        )}
        <span>{message}</span>
      </div>
      <div className="max-h-[650px] overflow-auto">
        <div className="relative w-max max-w-full">
          <canvas ref={canvas} className="h-auto max-w-full shadow" />
          {annotations
            .filter((item) => item.page_number === page)
            .map((item) => (
              <button
                key={item.id}
                title={`${item.comment || "Annotation"} · click to copy link; double-click to delete`}
                className="absolute min-h-0 border border-amber-500 bg-amber-300/40 p-0"
                style={{
                  left: `${item.geometry.x * 100}%`,
                  top: `${item.geometry.y * 100}%`,
                  width: `${item.geometry.width * 100}%`,
                  height: `${item.geometry.height * 100}%`,
                }}
                onClick={() => void copyLink(item)}
                onDoubleClick={() =>
                  void repositoryApi
                    .deleteAnnotation(item)
                    .then(() =>
                      setAnnotations((values) =>
                        values.filter((value) => value.id !== item.id),
                      ),
                    )
                }
              />
            ))}
        </div>
      </div>
    </div>
  );
}

function TablePreview({ version }: { version: RepositoryVersion }) {
  const [data, setData] = useState<TabularPreview>();
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState("");
  const [delimiter, setDelimiter] = useState("");
  const [encoding, setEncoding] = useState("");
  const firstColumn = data?.schema[0]?.name;
  useEffect(() => {
    const body: Record<string, unknown> = {
      page,
      page_size: 100,
      filters:
        filter && firstColumn
          ? [{ column: firstColumn, operator: "contains", value: filter }]
          : [],
      sort: sort ? [{ column: sort, direction: "asc" }] : [],
    };
    if (version.profile?.file_kind === "csv" && (delimiter || encoding)) {
      body.csv = {
        ...(delimiter ? { delimiter } : {}),
        ...(encoding ? { encoding } : {}),
      };
    }
    void repositoryApi.preview(version.id, body).then(setData);
  }, [
    version.id,
    version.profile?.file_kind,
    page,
    filter,
    sort,
    delimiter,
    encoding,
    firstColumn,
  ]);
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs">
        <input
          className="h-8 rounded border px-2"
          value={filter}
          onChange={(event) => {
            setPage(1);
            setFilter(event.target.value);
          }}
          placeholder="Filter first column"
        />
        <select
          className="h-8 rounded border bg-background px-2"
          value={sort}
          onChange={(event) => {
            setPage(1);
            setSort(event.target.value);
          }}
          aria-label="Sort column"
        >
          <option value="">No sort</option>
          {data?.schema.map((column) => (
            <option key={column.name} value={column.name}>
              {column.name} ascending
            </option>
          ))}
        </select>
        {version.profile?.file_kind === "csv" && (
          <>
            <select
              className="h-8 rounded border bg-background px-2"
              value={delimiter}
              onChange={(event) => setDelimiter(event.target.value)}
              aria-label="CSV delimiter"
            >
              <option value="">Detected delimiter</option>
              <option value=",">Comma</option>
              <option value=";">Semicolon</option>
              <option value={"\t"}>Tab</option>
              <option value="|">Pipe</option>
            </select>
            <select
              className="h-8 rounded border bg-background px-2"
              value={encoding}
              onChange={(event) => setEncoding(event.target.value)}
              aria-label="CSV encoding"
            >
              <option value="">Detected encoding</option>
              <option value="utf-8">UTF-8</option>
              <option value="utf-8-sig">UTF-8 BOM</option>
              <option value="windows-1252">Windows-1252</option>
            </select>
          </>
        )}
        <button
          className="rounded border px-2 py-1"
          disabled={page === 1}
          onClick={() => setPage((value) => value - 1)}
        >
          Previous
        </button>
        <span>
          Page {page} · {data?.total_rows.toLocaleString()} rows
        </span>
        <button
          className="rounded border px-2 py-1"
          disabled={!data || page * data.page_size >= data.total_rows}
          onClick={() => setPage((value) => value + 1)}
        >
          Next
        </button>
      </div>
      <div className="max-h-[560px] overflow-auto rounded border">
        <table className="w-max min-w-full text-xs">
          <thead className="sticky top-0 bg-background">
            <tr>
              {data?.schema.map((column) => (
                <th key={column.name} className="border-b p-2 text-left">
                  {column.name}
                  <small className="block font-normal text-muted-foreground">
                    {column.type}
                  </small>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data?.rows.map((row, index) => (
              <tr key={index}>
                {data.schema.map((column) => (
                  <td
                    key={column.name}
                    className="border-b p-2 whitespace-nowrap"
                  >
                    {String(row[column.name] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function OfficePreview({ version }: { version: RepositoryVersion }) {
  const host = useRef<HTMLDivElement>(null);
  const editor = useRef<{ destroyEditor: () => void }>();
  const [mode, setMode] = useState<"view" | "edit">(
    version.capabilities.can_edit ? "edit" : "view",
  );
  const [message, setMessage] = useState("");
  useEffect(() => {
    let active = true;
    void repositoryApi
      .office(version.id, mode)
      .then(({ document_server_url, config }) => {
        const start = () => {
          if (!active || !host.current || !window.DocsAPI) return;
          editor.current?.destroyEditor();
          editor.current = new window.DocsAPI.DocEditor(
            host.current.id,
            config,
          );
        };
        if (window.DocsAPI) start();
        else {
          const script = document.createElement("script");
          script.src = `${document_server_url.replace(/\/$/, "")}/web-apps/apps/api/documents/api.js`;
          script.onload = start;
          script.onerror = () => setMessage("ONLYOFFICE is unavailable");
          document.head.appendChild(script);
        }
      })
      .catch((error) =>
        setMessage(
          error instanceof Error ? error.message : "Office preview failed",
        ),
      );
    return () => {
      active = false;
      editor.current?.destroyEditor();
      editor.current = undefined;
    };
  }, [version.id, mode]);
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs">
        {version.capabilities.can_edit && (
          <select
            className="h-8 rounded border"
            value={mode}
            onChange={(event) => setMode(event.target.value as "view" | "edit")}
          >
            <option value="view">View</option>
            <option value="edit">Edit collaboratively</option>
          </select>
        )}
        <span>{message}</span>
      </div>
      <div
        id={`onlyoffice-${version.id}`}
        ref={host}
        className="h-[650px] min-h-[480px] overflow-hidden rounded border"
      />
    </div>
  );
}
