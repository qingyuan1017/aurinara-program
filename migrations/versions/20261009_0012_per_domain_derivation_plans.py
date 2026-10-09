"""Split single SDTM/ADaM Derivation Plans into per-domain / per-dataset plans.

Revision ID: 20261009_0012
Revises: 20261008_0011
Create Date: 2026-10-09
"""

import hashlib
import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261009_0012"
down_revision: str | None = "20261008_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fingerprint(value: Any) -> str:
    """Canonical fingerprint identical to ``app.common.canonical.fingerprint``."""

    canonical = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _injected_read_id(existing: set[str], owner_code: str) -> str:
    """Pick the first non-colliding injected read-node id for a sub-plan."""

    index = 1
    while True:
        candidate = f"__read_{owner_code}_{index}"
        if candidate not in existing:
            return candidate
        index += 1


def split_plan(
    payload: dict[str, Any],
    *,
    read_node_type: str,
    write_node_type: str,
    write_key: str,
    envelope_key: str,
    pin_key: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Split one all-domain/all-dataset DAG into deterministic per-owner sub-plans.

    Returns a list of ``{"code", "payload", "upstream_plan_pins"}`` sub-plan dicts
    and a ``node_id -> owning code`` map for annotation backfill.
    """

    nodes: list[dict[str, Any]] = list(payload.get("nodes", []))
    edges: list[dict[str, Any]] = list(payload.get("edges", []))
    nodes_by_id = {str(node["id"]): node for node in nodes}

    outgoing: dict[str, list[str]] = {str(node["id"]): [] for node in nodes}
    incoming: dict[str, list[str]] = {str(node["id"]): [] for node in nodes}
    for edge in edges:
        source = str(edge["source_node"])
        target = str(edge["target_node"])
        outgoing[source].append(target)
        incoming[target].append(source)

    # Map each write node to the code it produces.
    write_code_by_node: dict[str, str] = {
        str(node["id"]): str(node[write_key])
        for node in nodes
        if node.get("node_type") == write_node_type
    }
    written_codes = sorted(set(write_code_by_node.values()))
    if not written_codes:
        raise RuntimeError(
            "legacy derivation plan has no write node; cannot split into per-owner plans"
        )

    # For each node, compute the set of written codes it can reach (downstream).
    def reachable_codes(start: str) -> set[str]:
        codes: set[str] = set()
        stack = [start]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            if current in write_code_by_node:
                codes.add(write_code_by_node[current])
            stack.extend(outgoing[current])
        return codes

    consumers_by_node: dict[str, set[str]] = {
        node_id: reachable_codes(node_id) for node_id in nodes_by_id
    }

    # Deterministic ownership: a node reaching >= 2 codes is owned by the
    # lexicographically-smallest consuming code. A node reaching exactly one
    # code is owned by that code. A node reaching no code (dangling) is dropped
    # from per-owner sub-plans (it produces nothing and feeds nothing written).
    owner_by_node: dict[str, str] = {}
    for node_id, codes in consumers_by_node.items():
        if not codes:
            continue
        owner_by_node[node_id] = min(codes)

    sub_plans: list[dict[str, Any]] = []
    node_owner_map: dict[str, str] = dict(owner_by_node)

    for code in written_codes:
        # Nodes owned by this code.
        owned_ids = [node_id for node_id, owner in owner_by_node.items() if owner == code]
        # Nodes consumed by this code but owned by another code become injected reads.
        foreign_consumed = [
            node_id
            for node_id, codes in consumers_by_node.items()
            if code in codes and owner_by_node.get(node_id) != code
        ]
        existing_ids = set(owned_ids)
        sub_nodes: list[dict[str, Any]] = [dict(nodes_by_id[node_id]) for node_id in owned_ids]
        sub_edges: list[dict[str, Any]] = []
        owned_set = set(owned_ids)
        # Keep every edge whose both endpoints are owned by this code.
        for edge in edges:
            source = str(edge["source_node"])
            target = str(edge["target_node"])
            if source in owned_set and target in owned_set:
                sub_edges.append({"source_node": source, "target_node": target})

        # Inject a read node per foreign-owned source feeding an owned node, with
        # an edge to the first owned consumer of that shared node.
        injected: dict[str, str] = {}
        pin_owners: set[str] = set()
        for shared_id in foreign_consumed:
            shared_owner = owner_by_node[shared_id]
            owned_targets = [t for t in outgoing[shared_id] if t in owned_set]
            if not owned_targets:
                continue
            read_id = _injected_read_id(existing_ids, shared_owner)
            existing_ids.add(read_id)
            injected[shared_id] = read_id
            sub_nodes.append({"node_type": read_node_type, "id": read_id, "dataset": shared_owner})
            pin_owners.add(shared_owner)
            for target in owned_targets:
                sub_edges.append({"source_node": read_id, "target_node": target})

        # Assert per-plan id uniqueness before emitting.
        ids = [str(node["id"]) for node in sub_nodes]
        if len(ids) != len(set(ids)):
            raise RuntimeError(
                f"split produced duplicate node ids for code '{code}': {sorted(ids)}"
            )

        sub_payload = dict(payload)
        sub_payload["schema_version"] = "1.1.0"
        sub_payload[envelope_key] = code
        sub_payload["nodes"] = sub_nodes
        sub_payload["edges"] = sub_edges
        pins = sorted(
            ({pin_key: owner, "plan_revision": 1} for owner in pin_owners),
            key=lambda item: item[pin_key],
        )
        sub_plans.append({"code": code, "payload": sub_payload, "upstream_plan_pins": pins})

    return sub_plans, node_owner_map


def _split_table(
    bind: sa.engine.Connection,
    *,
    table: str,
    code_column: str,
    read_node_type: str,
    write_node_type: str,
    write_key: str,
    envelope_key: str,
    pin_key: str,
) -> dict[str, dict[str, str]]:
    """Backfill one plan table in place. Returns per-aggregate node->code maps."""

    rows = (
        bind.execute(
            sa.text(
                f"SELECT id, aggregate_id, study_id, revision, state, payload, "  # noqa: S608
                f"created_by, created_at FROM {table} ORDER BY aggregate_id, revision"
            )
        )
        .mappings()
        .all()
    )

    maps_by_aggregate: dict[str, dict[str, str]] = {}
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        sub_plans, node_map = split_plan(
            payload,
            read_node_type=read_node_type,
            write_node_type=write_node_type,
            write_key=write_key,
            envelope_key=envelope_key,
            pin_key=pin_key,
        )
        maps_by_aggregate[str(row["aggregate_id"])] = node_map
        # Delete the legacy row and emit per-owner revision=1 rows.
        bind.execute(
            sa.text(f"DELETE FROM {table} WHERE id = :id"),  # noqa: S608
            {"id": row["id"]},
        )
        for sub in sub_plans:
            bind.execute(
                sa.text(
                    f"INSERT INTO {table} "  # noqa: S608
                    f"(id, aggregate_id, study_id, {code_column}, revision, schema_version, "
                    "specification_revision, input_selection_revision, state, "
                    "upstream_plan_pins, alignment_reasons, payload, fingerprint, "
                    "created_by, created_at) VALUES "
                    "(gen_random_uuid(), :aggregate_id, :study_id, :code, 1, '1.1.0', "
                    ":spec_rev, :input_rev, :state, "
                    "CAST(:pins AS jsonb), CAST(:reasons AS jsonb), CAST(:payload AS jsonb), "
                    ":fingerprint, :created_by, :created_at)"
                ),
                {
                    "aggregate_id": row["aggregate_id"],
                    "study_id": row["study_id"],
                    "code": sub["code"],
                    "spec_rev": payload["specification_revision"],
                    "input_rev": payload["input_selection_revision"],
                    "state": row["state"],
                    "pins": json.dumps(sub["upstream_plan_pins"]),
                    # Invariant (design 2.3): alignment_reasons is empty iff state ==
                    # "aligned". An aligned row stores NULL (no reasons); a legacy row
                    # that was already misaligned at migration time must carry a
                    # non-empty reason. The pre-split model did not persist *why* it was
                    # misaligned, so emit the deterministic "specification_changed"
                    # marker (a re-save against the current Specification clears it).
                    "reasons": (
                        None if row["state"] == "aligned" else json.dumps(["specification_changed"])
                    ),
                    "payload": json.dumps(sub["payload"]),
                    "fingerprint": _fingerprint(sub["payload"]),
                    "created_by": row["created_by"],
                    "created_at": row["created_at"],
                },
            )
    return maps_by_aggregate


def _backfill_acrf_domain(
    bind: sa.engine.Connection, maps_by_aggregate: dict[str, dict[str, str]]
) -> None:
    rows = (
        bind.execute(sa.text("SELECT id, sdtm_id, links FROM sdtm_acrf_annotations"))
        .mappings()
        .all()
    )
    for row in rows:
        links = row["links"]
        if isinstance(links, str):
            links = json.loads(links)
        node_map = maps_by_aggregate.get(str(row["sdtm_id"]), {})
        changed = False
        for link in links:
            if link.get("target_type") != "derivation_plan_node":
                continue
            if link.get("domain") is not None:
                continue
            node_id = str(link.get("node_id"))
            domain = node_map.get(node_id)
            link["domain"] = domain  # may be None if node did not survive the split
            changed = True
        if changed:
            bind.execute(
                sa.text(
                    "UPDATE sdtm_acrf_annotations SET links = CAST(:links AS jsonb) WHERE id = :id"
                ),
                {"links": json.dumps(links), "id": row["id"]},
            )


def _stale_runs(bind: sa.engine.Connection, module_key: str, aggregate_ids: list[str]) -> None:
    if not aggregate_ids:
        return
    for table in ("validation_runs", "execution_runs"):
        bind.execute(
            sa.text(
                f"UPDATE {table} SET status = 'stale' "  # noqa: S608
                "WHERE module_key = :module AND status = 'succeeded' "
                "AND owner_id = ANY(:owners)"
            ),
            {"module": module_key, "owners": aggregate_ids},
        )


def upgrade() -> None:
    bind = op.get_bind()

    # SDTM — add nullable/new columns, split, backfill annotations, finalize keys.
    op.add_column(
        "sdtm_derivation_plan_revisions",
        sa.Column("domain_code", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "sdtm_derivation_plan_revisions",
        sa.Column(
            "upstream_plan_pins",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "sdtm_derivation_plan_revisions",
        sa.Column("alignment_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Drop the old (aggregate_id, revision) uniqueness BEFORE splitting: a legacy row
    # spanning N domains emits N per-domain rows that all start at revision=1, which the
    # old constraint would reject. Per-domain uniqueness is restored after the split.
    op.drop_constraint(
        "uq_sdtm_plan_aggregate_revision", "sdtm_derivation_plan_revisions", type_="unique"
    )
    sdtm_maps = _split_table(
        bind,
        table="sdtm_derivation_plan_revisions",
        code_column="domain_code",
        read_node_type="sdtm_read",
        write_node_type="domain_write",
        write_key="domain",
        envelope_key="domain",
        pin_key="domain_code",
    )
    _backfill_acrf_domain(bind, sdtm_maps)
    _stale_runs(bind, "sdtm", list(sdtm_maps.keys()))
    op.alter_column(
        "sdtm_derivation_plan_revisions",
        "domain_code",
        existing_type=sa.String(length=8),
        nullable=False,
    )
    op.alter_column(
        "sdtm_derivation_plan_revisions",
        "upstream_plan_pins",
        server_default=None,
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=False,
    )
    op.create_unique_constraint(
        "uq_sdtm_plan_aggregate_domain_revision",
        "sdtm_derivation_plan_revisions",
        ["aggregate_id", "domain_code", "revision"],
    )
    op.create_index(
        "ix_sdtm_plan_aggregate_domain",
        "sdtm_derivation_plan_revisions",
        ["aggregate_id", "domain_code"],
    )

    # ADaM — mirror.
    op.add_column(
        "adam_derivation_plan_revisions",
        sa.Column("dataset_code", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "adam_derivation_plan_revisions",
        sa.Column(
            "upstream_plan_pins",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "adam_derivation_plan_revisions",
        sa.Column("alignment_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Drop the old (aggregate_id, revision) uniqueness before splitting (see SDTM note).
    op.drop_constraint(
        "uq_adam_plan_aggregate_revision", "adam_derivation_plan_revisions", type_="unique"
    )
    adam_maps = _split_table(
        bind,
        table="adam_derivation_plan_revisions",
        code_column="dataset_code",
        read_node_type="adam_read",
        write_node_type="dataset_write",
        write_key="dataset",
        envelope_key="dataset",
        pin_key="dataset_code",
    )
    _stale_runs(bind, "adam", list(adam_maps.keys()))
    op.alter_column(
        "adam_derivation_plan_revisions",
        "dataset_code",
        existing_type=sa.String(length=8),
        nullable=False,
    )
    op.alter_column(
        "adam_derivation_plan_revisions",
        "upstream_plan_pins",
        server_default=None,
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=False,
    )
    op.create_unique_constraint(
        "uq_adam_plan_aggregate_dataset_revision",
        "adam_derivation_plan_revisions",
        ["aggregate_id", "dataset_code", "revision"],
    )
    op.create_index(
        "ix_adam_plan_aggregate_dataset",
        "adam_derivation_plan_revisions",
        ["aggregate_id", "dataset_code"],
    )


def _guard_downgrade(
    bind: sa.engine.Connection, *, table: str, code_column: str, read_node_type: str
) -> None:
    multi = bind.execute(
        sa.text(
            f"SELECT aggregate_id, COUNT(DISTINCT {code_column}) AS codes "  # noqa: S608
            f"FROM {table} GROUP BY aggregate_id HAVING COUNT(DISTINCT {code_column}) > 1"
        )
    ).first()
    if multi is not None:
        raise RuntimeError(
            f"cannot downgrade: aggregate {multi[0]} spans multiple {code_column} values; "
            "recombining split per-owner plans is lossy"
        )
    pinned = bind.execute(
        sa.text(
            f"SELECT id FROM {table} "  # noqa: S608
            "WHERE upstream_plan_pins <> '[]'::jsonb "
            f"OR payload::text LIKE :needle LIMIT 1"
        ),
        {"needle": f'%"node_type":"{read_node_type}"%'},
    ).first()
    if pinned is not None:
        raise RuntimeError(
            f"cannot downgrade: {table} contains injected {read_node_type} read pins; "
            "recombining split per-owner plans is lossy"
        )


def downgrade() -> None:
    bind = op.get_bind()
    _guard_downgrade(
        bind,
        table="sdtm_derivation_plan_revisions",
        code_column="domain_code",
        read_node_type="sdtm_read",
    )
    _guard_downgrade(
        bind,
        table="adam_derivation_plan_revisions",
        code_column="dataset_code",
        read_node_type="adam_read",
    )

    op.drop_index("ix_adam_plan_aggregate_dataset", table_name="adam_derivation_plan_revisions")
    op.drop_constraint(
        "uq_adam_plan_aggregate_dataset_revision",
        "adam_derivation_plan_revisions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_adam_plan_aggregate_revision",
        "adam_derivation_plan_revisions",
        ["aggregate_id", "revision"],
    )
    op.drop_column("adam_derivation_plan_revisions", "alignment_reasons")
    op.drop_column("adam_derivation_plan_revisions", "upstream_plan_pins")
    op.drop_column("adam_derivation_plan_revisions", "dataset_code")

    op.drop_index("ix_sdtm_plan_aggregate_domain", table_name="sdtm_derivation_plan_revisions")
    op.drop_constraint(
        "uq_sdtm_plan_aggregate_domain_revision",
        "sdtm_derivation_plan_revisions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_sdtm_plan_aggregate_revision",
        "sdtm_derivation_plan_revisions",
        ["aggregate_id", "revision"],
    )
    op.drop_column("sdtm_derivation_plan_revisions", "alignment_reasons")
    op.drop_column("sdtm_derivation_plan_revisions", "upstream_plan_pins")
    op.drop_column("sdtm_derivation_plan_revisions", "domain_code")
