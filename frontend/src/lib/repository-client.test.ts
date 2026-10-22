import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  repositoryApi,
  type PdfAnnotation,
  type RepositoryNode,
} from "./repository-client";

const node: RepositoryNode = {
  id: "node-1",
  study_id: "study-1",
  parent_id: null,
  kind: "file",
  display_name: "source.pdf",
  source_product: "platform",
  module: "repository",
  source_status: "available",
  classification: "internal",
  lifecycle_status: "active",
  revision: 7,
  current_version_number: 1,
  required_read_action: "platform.repository.read",
  required_write_action: "platform.repository.write",
  site_id: null,
  updated_at: "2026-01-01T00:00:00Z",
  current_version: null,
  capabilities: {
    can_preview: true,
    can_edit: false,
    can_annotate: true,
    can_manage: true,
    conversion_targets: [],
  },
};

describe("Repository Platform client", () => {
  beforeEach(() => {
    vi.stubGlobal("sessionStorage", { getItem: () => "token" });
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify(node), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("uses the server revision for node mutations", async () => {
    await repositoryApi.patch(node, { display_name: "renamed.pdf" });

    expect(fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/v1\/repository\/nodes\/node-1$/),
      expect.objectContaining({
        method: "PATCH",
        headers: expect.objectContaining({
          Authorization: "Bearer token",
          "If-Match": '"7"',
        }),
      }),
    );
  });

  it("uses optimistic concurrency for shared PDF annotation deletion", async () => {
    const annotation = {
      id: "annotation-1",
      version_id: "version-1",
      page_number: 1,
      geometry: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 },
      selected_text: null,
      comment: "Review",
      category: "comment",
      status: "open",
      style: {
        font_family: "Helvetica",
        font_size: 10,
        text_color: "#1f2937",
        fill_color: "#facc15",
        border_color: "#d97706",
        opacity: 0.32,
      },
      revision: 3,
    } satisfies PdfAnnotation;

    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }));
    await repositoryApi.deleteAnnotation(annotation);

    expect(fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/v1\/repository\/annotations\/annotation-1$/),
      expect.objectContaining({
        method: "DELETE",
        headers: expect.objectContaining({ "If-Match": '"3"' }),
      }),
    );
  });

  it("sends annotation appearance updates with optimistic concurrency", async () => {
    const annotation = {
      id: "annotation-1",
      version_id: "version-1",
      page_number: 1,
      geometry: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 },
      selected_text: "Source text",
      comment: "Review",
      category: "comment",
      status: "open",
      style: {
        font_family: "Helvetica",
        font_size: 10,
        text_color: "#1f2937",
        fill_color: "#facc15",
        border_color: "#d97706",
        opacity: 0.32,
      },
      revision: 3,
    } satisfies PdfAnnotation;
    const updated = {
      ...annotation,
      style: { ...annotation.style, font_family: "Courier" as const, font_size: 16 },
      revision: 4,
    };

    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(updated), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await repositoryApi.patchAnnotation(annotation, { style: updated.style });

    expect(fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/v1\/repository\/annotations\/annotation-1$/),
      expect.objectContaining({
        method: "PATCH",
        headers: expect.objectContaining({ "If-Match": '"3"' }),
        body: JSON.stringify({ style: updated.style }),
      }),
    );
  });
});
