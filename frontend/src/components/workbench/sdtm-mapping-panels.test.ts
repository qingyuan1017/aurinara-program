import { describe, expect, it } from "vitest";
import { domainsFrom, parseSources } from "./sdtm-mapping-panels";
import {
  appendUniqueCsvToken,
  applyDomainMappingTransfer,
  applyVariableMappingTransfer,
  outputArtifactSelections,
  resolveSelectedWorkarea,
} from "./sdtm-mapping-utils";

describe("SDTM mapping editors", () => {
  it("keeps ordered multi-source cells qualified by provider and dataset", () => {
    expect(parseSources("raw:demog.sex, sdtm:dm.usubjid")).toEqual([
      { source_type: "raw", dataset: "DEMOG", variable: "SEX" },
      { source_type: "sdtm", dataset: "DM", variable: "USUBJID" },
    ]);
  });

  it("rejects an unqualified cell source", () => {
    expect(() => parseSources("DEMOG.SEX")).toThrow(
      "Use raw:DATASET.VAR or sdtm:DOMAIN.VAR",
    );
  });

  it("retains Specification-owned VLM contexts for matrix columns", () => {
    const domains = domainsFrom({
      domains: [
        {
          code: "LB",
          variables: [{ name: "LBORRES" }],
          value_contexts: [
            {
              id: "chemistry",
              label: "Chemistry",
              discriminator_variable: "LBTESTCD",
              operator: "in",
              values: ["ALT", "AST"],
            },
          ],
        },
      ],
    });
    expect(domains[0]?.value_contexts?.[0]).toMatchObject({
      id: "chemistry",
      discriminator_variable: "LBTESTCD",
      values: ["ALT", "AST"],
    });
  });

  it("appends a dropped mapping source without replacing order or adding duplicates", () => {
    expect(appendUniqueCsvToken("raw:DM.USUBJID", "raw:AE.AETERM")).toBe(
      "raw:DM.USUBJID, raw:AE.AETERM",
    );
    expect(appendUniqueCsvToken("DM, AE", "dm")).toBe("DM, AE");
  });

  it("routes dragged datasets only to the matching Domain Mapping target", () => {
    const initial = { rawDatasets: "DM", upstreamDomains: "" };
    expect(
      applyDomainMappingTransfer(initial, {
        sourceId: "domain-source:raw:AE",
        targetId: "domain-target:raw",
      }),
    ).toEqual({ rawDatasets: "DM, AE", upstreamDomains: "" });
    expect(
      applyDomainMappingTransfer(initial, {
        sourceId: "domain-source:raw:AE",
        targetId: "domain-target:sdtm",
      }),
    ).toEqual(initial);
  });

  it("appends a dragged qualified variable to the selected Default or VLM cell", () => {
    expect(
      applyVariableMappingTransfer(
        { "LBORRES|chemistry": "raw:LABS.RESULT" },
        {
          sourceId: "variable-source:sdtm:DM.USUBJID",
          targetId: "variable-cell:LBORRES|chemistry",
        },
      ),
    ).toEqual({
      "LBORRES|chemistry": "raw:LABS.RESULT, sdtm:DM.USUBJID",
    });
  });

  it("does not fall back to an existing workarea while creating a new one", () => {
    const workareas = [
      { id: "existing-1", name: "Existing" },
      { id: "existing-2", name: "Alternative" },
    ];
    expect(resolveSelectedWorkarea(workareas, "", true)).toBeUndefined();
    expect(resolveSelectedWorkarea(workareas, "", false)).toEqual(workareas[0]);
    expect(resolveSelectedWorkarea(workareas, "existing-2", false)).toEqual(
      workareas[1],
    );
  });

  it("extracts exact XPT choices from the current Output Selection", () => {
    expect(
      outputArtifactSelections({
        items: [
          { domain: "DM", xpt_artifact_id: "artifact-dm" },
          { domain: "SV", xpt_artifact_id: "artifact-sv" },
        ],
      }),
    ).toEqual({ DM: "artifact-dm", SV: "artifact-sv" });
  });
});
