import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import {
  repositoryApi,
  waitForRepositoryJob,
  type PdfAnnotation,
  type PdfAnnotationStyle,
  type RepositoryNode,
  type RepositoryVersion,
} from "@/lib/repository-client";

const DEFAULT_STYLE: PdfAnnotationStyle = {
  font_family: "Helvetica",
  font_size: 10,
  text_color: "#1f2937",
  fill_color: "#facc15",
  border_color: "#d97706",
  opacity: 0.32,
};

type Draft = {
  id?: string;
  geometry: PdfAnnotation["geometry"];
  selected_text: string;
  comment: string;
  category: string;
  status: string;
  style: PdfAnnotationStyle;
};

const clamp = (value: number, minimum: number, maximum: number) =>
  Math.min(maximum, Math.max(minimum, value));
const alpha = (color: string, opacity: number) =>
  `${color}${Math.round(clamp(opacity, 0, 1) * 255)
    .toString(16)
    .padStart(2, "0")}`;
const makeDraft = (item?: PdfAnnotation): Draft =>
  item
    ? {
        id: item.id,
        geometry: { ...item.geometry },
        selected_text: item.selected_text || "",
        comment: item.comment || "",
        category: item.category,
        status: item.status,
        style: { ...DEFAULT_STYLE, ...item.style },
      }
    : {
        geometry: { x: 0.08, y: 0.08, width: 0.34, height: 0.1 },
        selected_text: "",
        comment: "",
        category: "comment",
        status: "open",
        style: { ...DEFAULT_STYLE },
      };

export function RepositoryPdfPreview({
  node,
  version,
  changed,
}: {
  node: RepositoryNode;
  version: RepositoryVersion;
  changed: () => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const pageElement = useRef<HTMLDivElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy>();
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [annotations, setAnnotations] = useState<PdfAnnotation[]>([]);
  const [draft, setDraft] = useState<Draft>();
  const [drawing, setDrawing] = useState(false);
  const [drawStart, setDrawStart] = useState<{ x: number; y: number }>();
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const dragRef = useRef<{ id: string; pointerId: number; offsetX: number; offsetY: number; moved: boolean } | undefined>(undefined);

  useEffect(() => {
    let active = true;
    let loaded: PDFDocumentProxy | undefined;
    void (async () => {
      try {
        const [{ url }, pdfjs, worker] = await Promise.all([
          repositoryApi.download(version.id),
          import("pdfjs-dist"),
          import("pdfjs-dist/build/pdf.worker.min.mjs?url"),
        ]);
        pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
        loaded = await pdfjs.getDocument({ url, disableRange: false }).promise;
        if (active) setPdf(loaded);
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "PDF preview failed");
      }
    })();
    return () => {
      active = false;
      void loaded?.cleanup();
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
        if (target) {
          setPage(target.page_number);
          setDraft(makeDraft(target));
        }
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
    setMessage(`${count} matching page${count === 1 ? "" : "s"}`);
  };

  const beginAnnotation = () => {
    setDraft(makeDraft());
    setDrawing(true);
    setConfirmDelete(false);
    setMessage("Drag on the page to place the annotation.");
  };
  const point = (event: { clientX: number; clientY: number }) => {
    const bounds = pageElement.current?.getBoundingClientRect();
    if (!bounds) return { x: 0, y: 0 };
    return {
      x: clamp((event.clientX - bounds.left) / bounds.width, 0, 1),
      y: clamp((event.clientY - bounds.top) / bounds.height, 0, 1),
    };
  };
  const beginAnnotationDrag = (event: ReactPointerEvent<HTMLButtonElement>, item: PdfAnnotation) => {
    event.stopPropagation();
    setDraft(makeDraft(item));
    setDrawing(false);
    setConfirmDelete(false);
    setMessage("");
    if (!version.capabilities.can_annotate) return;
    const current = point(event);
    dragRef.current = { id: item.id, pointerId: event.pointerId, offsetX: current.x - item.geometry.x, offsetY: current.y - item.geometry.y, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const moveAnnotation = (event: ReactPointerEvent<HTMLButtonElement>, item: PdfAnnotation) => {
    const drag = dragRef.current;
    if (!drag || drag.id !== item.id || drag.pointerId !== event.pointerId) return;
    event.stopPropagation();
    const current = point(event);
    const x = clamp(current.x - drag.offsetX, 0, 1 - item.geometry.width);
    const y = clamp(current.y - drag.offsetY, 0, 1 - item.geometry.height);
    if (Math.abs(x - item.geometry.x) > 0.002 || Math.abs(y - item.geometry.y) > 0.002) drag.moved = true;
    setDraft((value) => value?.id === item.id ? { ...value, geometry: { ...value.geometry, x, y } } : value);
  };
  const endAnnotationDrag = (event: ReactPointerEvent<HTMLButtonElement>, item: PdfAnnotation) => {
    const drag = dragRef.current;
    if (!drag || drag.id !== item.id || drag.pointerId !== event.pointerId) return;
    event.stopPropagation();
    dragRef.current = undefined;
    if (drag.moved) setMessage("Position updated. Save changes to share it with other users.");
  };
  const pointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drawing) return;
    const start = point(event);
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrawStart(start);
    setDraft((value) => ({
      ...(value || makeDraft()),
      geometry: { x: start.x, y: start.y, width: 0.01, height: 0.01 },
    }));
  };
  const pointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drawing || !drawStart) return;
    const current = point(event);
    const x = Math.min(drawStart.x, current.x);
    const y = Math.min(drawStart.y, current.y);
    setDraft((value) =>
      value
        ? {
            ...value,
            geometry: {
              x,
              y,
              width: Math.min(Math.max(0.01, Math.abs(current.x - drawStart.x)), 1 - x),
              height: Math.min(Math.max(0.01, Math.abs(current.y - drawStart.y)), 1 - y),
            },
          }
        : value,
    );
  };
  const pointerUp = () => {
    if (!drawStart) return;
    setDrawStart(undefined);
    setDrawing(false);
    setMessage("");
  };
  const setGeometry = (key: keyof PdfAnnotation["geometry"], percent: number) =>
    setDraft((value) => {
      if (!value) return value;
      const geometry = { ...value.geometry, [key]: clamp(percent / 100, 0, 1) };
      geometry.x = clamp(geometry.x, 0, 0.99);
      geometry.y = clamp(geometry.y, 0, 0.99);
      geometry.width = clamp(geometry.width, 0.01, 1 - geometry.x);
      geometry.height = clamp(geometry.height, 0.01, 1 - geometry.y);
      return { ...value, geometry };
    });

  const save = async () => {
    if (!draft?.comment.trim()) {
      setMessage("Annotation text is required.");
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      const body = {
        geometry: draft.geometry,
        selected_text: draft.selected_text.trim() || null,
        comment: draft.comment.trim(),
        category: draft.category,
        status: draft.status,
        style: draft.style,
      };
      if (draft.id) {
        const original = annotations.find((item) => item.id === draft.id);
        if (!original) return;
        const updated = await repositoryApi.patchAnnotation(original, body);
        setAnnotations((values) =>
          values.map((item) => (item.id === updated.id ? updated : item)),
        );
      } else {
        const created = await repositoryApi.annotate(version.id, {
          page_number: page,
          ...body,
        });
        setAnnotations((values) => [...values, created]);
      }
      setDraft(undefined);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save annotation");
    } finally {
      setSaving(false);
    }
  };
  const remove = useCallback(async (item: PdfAnnotation) => {
    try {
      await repositoryApi.deleteAnnotation(item);
      setAnnotations((values) => values.filter((value) => value.id !== item.id));
      setDraft(undefined);
      setConfirmDelete(false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not delete annotation");
    }
  }, []);
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.matches('input, textarea, select, [contenteditable="true"]')) return;
      if (event.key === "Escape" && draft) {
        setDraft(undefined); setDrawing(false); setConfirmDelete(false); setMessage("");
        return;
      }
      if ((event.key !== "Delete" && event.key !== "Backspace") || !draft?.id || saving || !version.capabilities.can_annotate) return;
      const item = annotations.find((value) => value.id === draft.id);
      if (!item) return;
      event.preventDefault();
      if (confirmDelete) void remove(item);
      else { setConfirmDelete(true); setMessage("Press Delete or Backspace again to remove this shared annotation."); }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [annotations, confirmDelete, draft, remove, saving, version.capabilities.can_annotate]);
  const copyLink = (item: PdfAnnotation) =>
    navigator.clipboard.writeText(
      `${location.origin}${location.pathname}?study=${node.study_id}&version=${version.id}&annotation=${item.id}`,
    );
  const overlayStyle = (value: Draft | PdfAnnotation) => {
    const style = { ...DEFAULT_STYLE, ...value.style };
    return {
      left: `${value.geometry.x * 100}%`,
      top: `${value.geometry.y * 100}%`,
      width: `${value.geometry.width * 100}%`,
      height: `${value.geometry.height * 100}%`,
      backgroundColor: alpha(style.fill_color, style.opacity),
      borderColor: style.border_color,
      color: style.text_color,
      fontFamily:
        style.font_family === "Times-Roman"
          ? "Times New Roman"
          : style.font_family,
      fontSize: `${style.font_size}px`,
    };
  };
  const current = annotations.filter((item) => item.page_number === page);
  const annotationNavigation = [...annotations].sort(
    (left, right) => left.page_number - right.page_number || left.id.localeCompare(right.id),
  );

  return (
    <div className="grid h-full min-h-[560px] grid-rows-[auto_auto_minmax(0,1fr)] gap-3">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-background p-2 text-xs">
        <button className="h-8 rounded border px-3" disabled={page <= 1} onClick={() => { setPage((value) => value - 1); setDraft(undefined); }}>Previous</button>
        <strong className="min-w-20 text-center">{page} / {pdf?.numPages || "…"}</strong>
        <button className="h-8 rounded border px-3" disabled={!pdf || page >= pdf.numPages} onClick={() => { setPage((value) => value + 1); setDraft(undefined); }}>Next</button>
        <div className="flex min-w-52 flex-1 items-center gap-2">
          <input className="h-8 w-full max-w-80 rounded border px-2" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search this PDF" />
          <button className="h-8 rounded border px-3" onClick={() => void search()}>Search</button>
        </div>
        {version.capabilities.can_annotate && <>
          <button className="h-8 rounded bg-primary px-3 text-primary-foreground" onClick={beginAnnotation}>+ Add annotation</button>
          <button className="h-8 rounded border px-3" onClick={() => void repositoryApi.exportPdf(version.id, node.display_name.replace(/\.pdf$/i, "") + "-annotated.pdf").then(waitForRepositoryJob).then(changed)}>Export annotated</button>
        </>}
      </div>
      {message && <div className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">{message}</div>}
      <div className="grid min-h-0 overflow-hidden rounded-xl border bg-muted/40 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-h-[480px] justify-center overflow-auto p-4 lg:p-6">
          <div ref={pageElement} className={`relative h-fit w-max max-w-full bg-white shadow-xl ${drawing ? "cursor-crosshair touch-none ring-4 ring-primary/60" : ""}`} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp}>
            <canvas ref={canvas} className="block h-auto max-w-full" />
            {current.map((item) => {
              const displayed = draft?.id === item.id ? draft : item;
              return <button key={item.id} type="button" title="Click to edit. Drag to reposition." className={`absolute touch-none cursor-grab overflow-hidden whitespace-pre-wrap rounded-sm border-2 p-1 text-left leading-tight active:cursor-grabbing ${draft?.id === item.id ? "ring-4 ring-primary ring-offset-2" : "hover:ring-2 hover:ring-primary"}`} style={overlayStyle(displayed)} onPointerDown={(event) => beginAnnotationDrag(event, item)} onPointerMove={(event) => moveAnnotation(event, item)} onPointerUp={(event) => endAnnotationDrag(event, item)} onPointerCancel={(event) => endAnnotationDrag(event, item)} onClick={(event) => { event.stopPropagation(); if (event.detail === 0) setDraft(makeDraft(item)); }}>{displayed.comment}</button>;
            })}
            {draft && !draft.id && (!drawing || drawStart) && <div className="pointer-events-none absolute overflow-hidden whitespace-pre-wrap rounded-sm border-2 border-dashed p-1 text-left leading-tight ring-4 ring-primary ring-offset-2" style={overlayStyle(draft)}>{draft.comment || "Type annotation text →"}</div>}
          </div>
        </div>
        <aside className="min-h-0 overflow-auto border-t bg-background p-4 lg:border-l lg:border-t-0">
          <div className="flex items-center justify-between border-b pb-3">
            <div><p className="text-[10px] font-bold tracking-widest text-muted-foreground">{draft ? `PAGE ${page}` : `${annotations.length} TOTAL`}</p><h3 className="font-semibold">{draft ? draft.id ? "Edit annotation" : "New annotation" : "Annotation navigation"}</h3></div>
            <span className="grid h-7 w-7 place-items-center rounded-full bg-muted text-xs font-bold">{draft ? current.length : annotations.length}</span>
          </div>
          <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">Click to edit · Drag to move · Delete twice to remove · Esc to close</p>
          {draft ? <div className="grid gap-3 pt-4 text-xs">
            <label className="grid gap-1"><span className="font-medium">Annotation text</span><textarea autoFocus={!draft.id} className="min-h-20 rounded-md border p-2" value={draft.comment} onChange={(event) => setDraft({ ...draft, comment: event.target.value })} placeholder="What should reviewers see?" /></label>
            <label className="grid gap-1"><span className="font-medium">Referenced PDF text <em className="font-normal text-muted-foreground">optional</em></span><textarea className="min-h-16 rounded-md border p-2" value={draft.selected_text} onChange={(event) => setDraft({ ...draft, selected_text: event.target.value })} placeholder="Paste the source text this note refers to" /></label>
            <fieldset className="rounded-lg border p-3"><legend className="px-1 font-semibold">Position & size <span className="font-normal text-muted-foreground">(% of page)</span></legend><div className="grid grid-cols-2 gap-2">{(["x", "y", "width", "height"] as const).map((key) => <label key={key} className="grid gap-1"><span className="text-muted-foreground">{{ x: "Left", y: "Top", width: "Width", height: "Height" }[key]}</span><input className="h-8 rounded border px-2" type="number" min="0" max="100" step="0.5" value={(draft.geometry[key] * 100).toFixed(1)} onChange={(event) => setGeometry(key, Number(event.target.value))} /></label>)}</div><button className="mt-2 h-8 w-full rounded border" onClick={() => setDrawing(true)}>Draw placement on page</button></fieldset>
            <fieldset className="rounded-lg border p-3"><legend className="px-1 font-semibold">Typography</legend><div className="grid grid-cols-2 gap-2"><label className="grid gap-1"><span className="text-muted-foreground">Font</span><select className="h-8 rounded border px-2" value={draft.style.font_family} onChange={(event) => setDraft({ ...draft, style: { ...draft.style, font_family: event.target.value as PdfAnnotationStyle["font_family"] } })}><option>Helvetica</option><option>Times-Roman</option><option>Courier</option></select></label><label className="grid gap-1"><span className="text-muted-foreground">Size (pt)</span><input className="h-8 rounded border px-2" type="number" min="6" max="48" value={draft.style.font_size} onChange={(event) => setDraft({ ...draft, style: { ...draft.style, font_size: clamp(Number(event.target.value), 6, 48) } })} /></label></div></fieldset>
            <fieldset className="rounded-lg border p-3"><legend className="px-1 font-semibold">Colors</legend><div className="grid grid-cols-3 gap-2">{(["text_color", "fill_color", "border_color"] as const).map((key) => <label key={key} className="grid gap-1"><span className="text-muted-foreground">{{ text_color: "Text", fill_color: "Fill", border_color: "Border" }[key]}</span><input className="h-8 w-full cursor-pointer rounded border p-1" type="color" value={draft.style[key]} onChange={(event) => setDraft({ ...draft, style: { ...draft.style, [key]: event.target.value } })} /></label>)}</div><label className="mt-3 grid grid-cols-[auto_1fr_auto] items-center gap-2"><span>Opacity</span><input type="range" min="0.05" max="1" step="0.05" value={draft.style.opacity} onChange={(event) => setDraft({ ...draft, style: { ...draft.style, opacity: Number(event.target.value) } })} /><output>{Math.round(draft.style.opacity * 100)}%</output></label></fieldset>
            <div className="grid grid-cols-2 gap-2"><label className="grid gap-1"><span>Category</span><select className="h-8 rounded border px-2" value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value })}><option value="comment">Comment</option><option value="issue">Issue</option><option value="highlight">Highlight</option><option value="note">Note</option></select></label><label className="grid gap-1"><span>Status</span><select className="h-8 rounded border px-2" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}><option value="open">Open</option><option value="resolved">Resolved</option></select></label></div>
            <div className="flex justify-end gap-2"><button className="h-8 rounded border px-3" onClick={() => { setDraft(undefined); setDrawing(false); setMessage(""); }}>Cancel</button><button className="h-8 rounded bg-primary px-3 text-primary-foreground disabled:opacity-50" disabled={saving || !draft.comment.trim()} onClick={() => void save()}>{saving ? "Saving…" : draft.id ? "Save changes" : "Create annotation"}</button></div>
            {draft.id && <div className="flex flex-wrap items-center gap-2 border-t pt-3"><button className="h-8 rounded border px-3" onClick={() => { const item = annotations.find((value) => value.id === draft.id); if (item) void copyLink(item); }}>Copy deep link</button>{confirmDelete ? <><span className="text-destructive">Delete shared note?</span><button className="h-8 rounded bg-destructive px-3 text-destructive-foreground" onClick={() => { const item = annotations.find((value) => value.id === draft.id); if (item) void remove(item); }}>Delete</button><button className="h-8 rounded border px-3" onClick={() => setConfirmDelete(false)}>Keep</button></> : <button className="h-8 rounded border border-destructive px-3 text-destructive" onClick={() => setConfirmDelete(true)}>Delete annotation</button>}</div>}
          </div> : <div className="grid gap-3 pt-4 text-xs">
            <div className="flex items-start justify-between gap-3 rounded-lg border bg-muted/40 p-3"><div><strong className="text-sm">Review the document</strong><p className="mt-1 leading-relaxed text-muted-foreground">Select a note to jump to its page and edit it.</p></div>{version.capabilities.can_annotate && <button className="h-8 shrink-0 rounded bg-primary px-3 text-primary-foreground" onClick={beginAnnotation}>+ Add</button>}</div>
            {annotationNavigation.length ? <nav aria-label="Document annotations" className="grid gap-2">{annotationNavigation.map((item) => <button key={item.id} className={`grid min-h-14 grid-cols-[5px_34px_minmax(0,1fr)] items-stretch gap-2 rounded-md border p-2 text-left ${item.page_number === page ? "border-primary bg-primary/5" : "hover:bg-muted/60"}`} onClick={() => { setPage(item.page_number); setDraft(makeDraft(item)); setDrawing(false); setConfirmDelete(false); setMessage(""); }}><span className="rounded" style={{ backgroundColor: item.style?.border_color || DEFAULT_STYLE.border_color }} /><span className="grid place-items-center rounded-md bg-muted font-bold text-primary">P{item.page_number}</span><span className="min-w-0 self-center"><strong className="block truncate">{item.comment || "Untitled annotation"}</strong><small className="capitalize text-muted-foreground">{item.category} · {item.status}</small></span></button>)}</nav> : <div className="rounded-lg border border-dashed bg-muted/40 p-4"><strong className="text-sm">No annotations yet</strong><p className="my-2 leading-relaxed text-muted-foreground">Add a precisely positioned review note to start the document conversation.</p>{version.capabilities.can_annotate && <button className="h-8 rounded bg-primary px-3 text-primary-foreground" onClick={beginAnnotation}>Create annotation</button>}</div>}
          </div>}
        </aside>
      </div>
    </div>
  );
}
