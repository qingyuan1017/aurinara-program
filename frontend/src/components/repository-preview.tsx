import { useEffect, useRef, useState } from "react";
import {
  repositoryApi,
  type RepositoryNode,
  type RepositoryVersion,
  type TabularPreview,
} from "@/lib/repository-client";
import { RepositoryPdfPreview } from "@/components/repository-pdf-preview";

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
    return <RepositoryPdfPreview node={node} version={version} changed={changed} />;
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
    <div className="grid h-full min-h-[520px] grid-rows-[auto_minmax(0,1fr)] gap-2">
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
    <div className="grid h-full min-h-[520px] grid-rows-[auto_minmax(0,1fr)] gap-2">
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
        className="h-full min-h-[520px] overflow-hidden rounded-lg border bg-background"
      />
    </div>
  );
}
