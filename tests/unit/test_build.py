"""The build compiler: transform, export, the three outcomes and the staged write.

The real workbook cannot produce a READY build yet — twelve red action items are open and
the call number is still a placeholder — so these tests drive the compiler with fixtures
whose blockers are cleared. That is the point of a fixture: to reach the state the real
workbook has not reached, and prove the machinery works when it does.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from apex_ads.compile_.build import DO_NOT_IMPORT, LATEST, BuildResult, Outcome, run_build
from apex_ads.compile_.editor_export import NotPausedError, UnmappedFieldError, write_all
from apex_ads.compile_.transform import PAUSED, transform
from apex_ads.exit_codes import ExitCode
from apex_ads.ingest.urlcheck import UrlResult
from apex_ads.ingest.workbook import parse_workbook
from apex_ads.models.config import Config, Rules, WorkbookSchema
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.validate.registry import validators_for
from apex_ads.validate.runner import run


def _url_results(status: str, paths: list[str]) -> dict[str, UrlResult]:
    return {
        path: UrlResult(
            url=f"https://www.apexhospitals.com{path}",
            status=status,  # type: ignore[arg-type]
            reason=status.lower(),
            http_status=200 if status == "PASS" else None,
        )
        for path in paths
    }


def _launchable(bundle: WorkbookBundle) -> WorkbookBundle:
    """The fixture with its launch blockers cleared: closed actions, a real call asset."""
    campaigns = [
        campaign.model_copy(
            update={
                "call_phone_number": "+91 141 000 0000",
                "call_schedule": "Mon-Sat 08:00-20:00 IST",
            }
        )
        for campaign in bundle.campaigns
    ]
    closed = [action.model_copy(update={"status": "Done"}) for action in bundle.blocking_actions]
    running = [action.model_copy(update={"status": "Done"}) for action in bundle.running_actions]
    return bundle.model_copy(
        update={"campaigns": campaigns, "blocking_actions": closed, "running_actions": running}
    )


@pytest.fixture()
def launchable(fixtures: dict[str, Path], schema: WorkbookSchema) -> WorkbookBundle:
    return _launchable(parse_workbook(fixtures["clean"], schema))


def verified(config: Config) -> Config:
    """A config whose Editor column names have been reconciled against a real export.

    Flipping this in a test is how the READY path gets exercised before Gaurav supplies
    an export. It is not a way to make a real build READY: `config/editor_schema.yaml`
    ships `verified: false`, and only a human who has actually done the reconciliation
    may change it.
    """
    schema = config.editor_schema
    return config.model_copy(
        update={
            "editor_schema": schema.model_copy(
                update={
                    "verified": True,
                    "verified_against": schema.verified_against.model_copy(
                        update={
                            "export_date": "2026-08-20",
                            "editor_version": "Google Ads Editor 2.9 (test double)",
                            "source_sha256": "3b8f2c1a"
                            * 8,  # a plausible digest, not a row of zeros
                            "reconciled_by": "test",
                        }
                    ),
                }
            )
        }
    )


def build(
    bundle: WorkbookBundle,
    config: Config,
    rules: Rules,
    out: Path,
    *,
    url_status: str = "PASS",
) -> BuildResult:
    urls = _url_results(url_status, [page.planned_url for page in bundle.landing_pages])
    result = run(bundle, rules, validators=validators_for(urls), mode="build")
    return run_build(
        bundle,
        config.model_copy(update={"rules": rules}),
        result,
        urls,
        out_root=out,
        run_id="20260818-120000-abcd1234",
        write_report=lambda directory, outcome: (directory / "PRE_FLIGHT_REPORT.txt").write_text(
            f"RESULT: BUILD {outcome.value}\n", encoding="utf-8"
        ),
    )


# ------------------------------------------------------------------------ transform


def test_every_compiled_campaign_is_paused(
    launchable: WorkbookBundle, fixture_rules: Rules
) -> None:
    """Acceptance test 2, at the transform. Asserted again at the writer."""
    account = transform(launchable, fixture_rules)
    assert account.campaigns
    assert {campaign.status for campaign in account.campaigns} == {PAUSED}
    assert {group.status for group in account.ad_groups} == {PAUSED}


def test_the_writer_refuses_a_row_that_is_not_paused(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """Guardrail §18.15: the second, independent assertion.

    If the transform were ever changed to emit an enabled campaign, the export still
    refuses to write it.
    """
    account = transform(launchable, fixture_rules)
    account.campaigns = [account.campaigns[0].model_copy(update={"status": "Enabled"})]

    with pytest.raises(NotPausedError):
        write_all(tmp_path, account, config.editor_schema)


def test_output_is_deterministic(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """Acceptance test 14: two runs of one workbook produce byte-identical files."""
    first = build(launchable, verified(config), fixture_rules, tmp_path / "one")
    second = build(launchable, verified(config), fixture_rules, tmp_path / "two")

    for a, b in zip(
        sorted(first.files, key=lambda f: f.path.name),
        sorted(second.files, key=lambda f: f.path.name),
        strict=True,
    ):
        assert a.path.name == b.path.name
        assert a.path.read_bytes() == b.path.read_bytes(), a.path.name


# -------------------------------------------------------------------------- outcomes


def test_a_clean_workbook_builds_ready(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """Acceptance test 1 — with the Editor schema verified."""
    result = build(launchable, verified(config), fixture_rules, tmp_path)

    assert result.outcome is Outcome.READY
    assert result.outcome.exit_code == ExitCode.OK
    written = {file.path.name for file in result.files}
    assert written == {
        "campaigns.csv",
        "adgroups.csv",
        "keywords.csv",
        "account_negatives.csv",
        "shared_negative_lists.csv",
        "campaign_negatives.csv",
        "adgroup_negatives.csv",
    }
    assert (result.directory / "MANUAL_STEPS.md").is_file()
    assert (result.directory / "manifest.json").is_file()
    assert not (result.directory / DO_NOT_IMPORT).exists()


def test_unverified_destinations_produce_a_quarantined_draft(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """Acceptance test 13 at build level: UNKNOWN never yields a deployable build."""
    result = build(launchable, config, fixture_rules, tmp_path, url_status="UNKNOWN")

    assert result.outcome is Outcome.DRAFT
    assert result.outcome.exit_code == ExitCode.DRAFT
    assert result.directory.name.endswith(".DRAFT")
    notice = (result.directory / DO_NOT_IMPORT).read_text(encoding="utf-8")
    assert "DO NOT IMPORT" in notice
    assert not (tmp_path / LATEST).exists(), "a DRAFT must be invisible to `latest`"


def test_a_blocked_workbook_writes_no_csvs(
    fixtures: dict[str, Path],
    schema: WorkbookSchema,
    fixture_rules: Rules,
    config: Config,
    tmp_path: Path,
) -> None:
    """Acceptance tests 3 and 15: a failed build leaves the report and nothing else."""
    bundle = _launchable(parse_workbook(fixtures["broad_positive"], schema))
    result = build(bundle, config, fixture_rules, tmp_path)

    assert result.outcome is Outcome.FAILED
    assert result.outcome.exit_code == ExitCode.BLOCKER
    assert result.files == []
    written = {path.name for path in result.directory.iterdir()}
    assert written == {"PRE_FLIGHT_REPORT.txt"}
    assert not list(tmp_path.glob("*.partial")), "no staging directory may survive"


def test_latest_follows_ready_builds_only(
    launchable: WorkbookBundle,
    fixtures: dict[str, Path],
    schema: WorkbookSchema,
    fixture_rules: Rules,
    config: Config,
    tmp_path: Path,
) -> None:
    build(launchable, verified(config), fixture_rules, tmp_path)
    pointer = tmp_path / LATEST
    assert pointer.exists() or (tmp_path / f"{LATEST}.txt").exists()


# ---------------------------------------------------------------------- Editor files


def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    text = path.read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(text.splitlines()))
    headers = list(rows[0]) if rows else []
    return headers, rows


def test_campaign_rows_are_paused_in_the_file(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """Acceptance test 2, at the artifact a human actually imports."""
    result = build(launchable, verified(config), fixture_rules, tmp_path)
    _, rows = _read(result.directory / "campaigns.csv")
    assert rows
    assert {row["Campaign Status"] for row in rows} == {"Paused"}


def test_files_use_the_editor_csv_dialect(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    result = build(launchable, verified(config), fixture_rules, tmp_path)
    raw = (result.directory / "campaigns.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "Editor expects a UTF-8 BOM"
    assert b"\r\n" in raw


def test_negatives_keep_their_four_scopes(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """Acceptance test 40 — the export must not flatten the hierarchy (Decision A4)."""
    result = build(launchable, verified(config), fixture_rules, tmp_path)
    names = {file.path.name for file in result.files}

    assert "negatives.csv" not in names, "one flat negatives file destroys the architecture"
    assert {
        "account_negatives.csv",
        "shared_negative_lists.csv",
        "campaign_negatives.csv",
        "adgroup_negatives.csv",
    } <= names

    _, shared = _read(result.directory / "shared_negative_lists.csv")
    _, campaign = _read(result.directory / "campaign_negatives.csv")
    shared_terms = {row["Keyword"] for row in shared}
    assert shared_terms
    assert not (shared_terms & {row["Keyword"] for row in campaign}), (
        "a shared list must not be expanded into campaign negatives for import convenience"
    )


def test_a_shared_list_row_names_its_campaigns(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    result = build(launchable, verified(config), fixture_rules, tmp_path)
    _, rows = _read(result.directory / "shared_negative_lists.csv")
    assert rows
    assert {row["Keyword List"] for row in rows} == {"ROUTE_BRAND"}
    assert all(row["Campaign"] for row in rows)


# -------------------------------------------------------------- no field disappears


def test_an_unmapped_field_blocks_the_build(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """Acceptance test 17, and the Phase-5 parking-lot requirement.

    A workbook column nobody classified must not vanish into a deployable build.
    """
    schema = config.editor_schema
    campaigns = schema.entities["campaigns"]
    stripped = campaigns.model_copy(update={"documentation_only": [], "manual_only": []})
    broken = config.model_copy(
        update={
            "editor_schema": schema.model_copy(
                update={"entities": {**schema.entities, "campaigns": stripped}}
            ),
            "rules": fixture_rules,
        }
    )

    urls = _url_results("PASS", [page.planned_url for page in launchable.landing_pages])
    result = run(launchable, fixture_rules, validators=validators_for(urls), mode="build")
    outcome = run_build(
        launchable,
        broken,
        result,
        urls,
        out_root=tmp_path,
        run_id="run-x",
        write_report=lambda directory, _: (directory / "PRE_FLIGHT_REPORT.txt").write_text(
            "x", encoding="utf-8"
        ),
    )

    assert outcome.outcome is Outcome.FAILED
    assert outcome.files == []
    unmapped = [f for f in outcome.findings if f.rule_id == "EXP-001"]
    assert unmapped, "an unclassified field must be reported, not dropped"
    assert "UNMAPPED SOURCE FIELD" in unmapped[0].message


def test_a_required_column_with_no_value_raises(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    account = transform(launchable, fixture_rules)
    account.campaigns = [account.campaigns[0].model_copy(update={"name": ""})]
    with pytest.raises(UnmappedFieldError):
        write_all(tmp_path, account, config.editor_schema)


# ------------------------------------------------------------------------- manifest


def test_manifest_traces_the_build_to_its_inputs(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """Acceptance test 16."""
    result = build(launchable, verified(config), fixture_rules, tmp_path)
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["run_id"] == result.run_id
    assert manifest["outcome"] == "READY"
    assert manifest["editor_schema_verified"] is True
    assert manifest["verified_against"]["export_date"] == "2026-08-20"
    assert manifest["workbook"]["sha256"] == launchable.source_sha256
    assert set(manifest["config_sha256"]) == {"rules", "workbook_schema", "editor_schema"}
    assert manifest["counts"]["campaigns"] == len(launchable.campaigns)
    assert {file["name"] for file in manifest["files"]} == {file.path.name for file in result.files}
    assert all(len(file["sha256"]) == 64 for file in manifest["files"])


def test_manual_steps_lists_what_editor_cannot_do(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    result = build(launchable, verified(config), fixture_rules, tmp_path)
    text = (result.directory / "MANUAL_STEPS.md").read_text(encoding="utf-8")

    assert "conversion" in text.casefold()
    assert "Check changes" in text
    assert "Paused" in text
    assert "sign-off" in text.casefold()


# ------------------------------------------- READY means import-ready, not "logic passed"


def test_an_unverified_editor_schema_can_never_be_ready(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """The blocking correction: guessed column names are not a deployable build.

    Everything else here is perfect — no blockers, every destination verified. The build
    is still a DRAFT, because the one contract that decides whether Google understands
    the files has not been checked.
    """
    assert config.editor_schema.verified is False, "the shipped config must stay unverified"

    result = build(launchable, config, fixture_rules, tmp_path, url_status="PASS")

    assert result.outcome is Outcome.DRAFT
    assert result.outcome.exit_code == ExitCode.DRAFT
    assert result.directory.name.endswith(".DRAFT")
    assert not (tmp_path / LATEST).exists()

    notice = (result.directory / DO_NOT_IMPORT).read_text(encoding="utf-8")
    assert "EDITOR COLUMN NAMES UNVERIFIED" in notice
    assert "LANDING PAGES UNVERIFIED" not in notice, "only the reasons that apply"


def test_the_notice_names_every_open_contract(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    result = build(launchable, config, fixture_rules, tmp_path, url_status="UNKNOWN")
    notice = (result.directory / DO_NOT_IMPORT).read_text(encoding="utf-8")
    assert "EDITOR COLUMN NAMES UNVERIFIED" in notice
    assert "LANDING PAGES UNVERIFIED" in notice


def test_verification_provenance_is_recorded(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """When somebody says it is verified, the manifest records against what."""
    result = build(launchable, verified(config), fixture_rules, tmp_path)
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
    provenance = manifest["verified_against"]
    assert provenance["export_date"]
    assert provenance["editor_version"]
    assert provenance["source_sha256"]
    assert provenance["reconciled_by"]


# ------------------------------------------------- no record type disappears either


def test_rsas_and_assets_reach_the_compiled_account(
    launchable: WorkbookBundle, fixture_rules: Rules
) -> None:
    """They were absent from CompiledAccount entirely, so nothing could notice them."""
    account = transform(launchable, fixture_rules)
    assert account.ads, "responsive search ads must survive the transform"
    assert account.supporting_assets, "supporting assets must survive the transform"
    assert set(account.collections()) >= {"ads", "supporting_assets"}


def test_every_compiled_record_type_has_a_declared_destination(config: Config) -> None:
    """The inventory must cover the compiler's whole output, not just the easy parts."""
    from apex_ads.compile_.transform import CompiledAccount

    declared = set(config.editor_schema.inventory)
    produced = set(CompiledAccount().collections())
    assert produced <= declared, f"undeclared record types: {sorted(produced - declared)}"


def test_an_undeclared_record_type_blocks_the_build(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """Acceptance test 17's entity-level twin (EXP-002).

    EXP-001 catches a field nobody mapped. It cannot see a record type that never reaches
    the exporter — which is exactly how nine RSAs went missing from a build that called
    itself READY.
    """
    schema = config.editor_schema
    without_ads = {k: v for k, v in schema.inventory.items() if k != "ads"}
    broken = verified(config).model_copy(
        update={"editor_schema": schema.model_copy(update={"inventory": without_ads})}
    )

    result = build(launchable, broken, fixture_rules, tmp_path)

    assert result.outcome is Outcome.FAILED
    assert result.files == []
    inventory = [f for f in result.findings if f.rule_id == "EXP-002"]
    assert inventory, "an undeclared record type must block, not vanish"
    assert "EXPORT INVENTORY" in inventory[0].message
    assert "ads" in inventory[0].message


def test_manual_steps_enumerates_every_ad_and_asset(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """Route B of the correction: what Editor does not import must be written out in full.

    A count is not a specification — a person retyping ad copy needs the copy.
    """
    account = transform(launchable, fixture_rules)
    result = build(launchable, verified(config), fixture_rules, tmp_path)
    text = (result.directory / "MANUAL_STEPS.md").read_text(encoding="utf-8")

    assert "Responsive search ads" in text
    assert "Supporting assets" in text

    for ad in account.ads:
        assert f"{ad.campaign} / {ad.ad_group}" in text
        for asset in ad.headlines + ad.descriptions:
            assert asset.text in text, f"missing asset text: {asset.text!r}"

    for asset in account.supporting_assets:
        assert asset.text_header in text, f"missing asset: {asset.text_header!r}"


# ------------------------------------------------- route integrity, not just labelling


def test_a_destination_without_a_handler_blocks_the_build(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """`EXP-002` must check the conveyor belt exists, not just the label.

    This is the exact one-line change somebody will make after the schema is verified:
    `ads: manual_steps` becomes `ads: editor`. Before this guard it produced a READY
    build with seven files, no ads in any of them, no finding, and MANUAL_STEPS silently
    dropping them — the inventory declaring everything accounted for while nine ads
    disappeared.

    **This test inverts when RSA Editor export is implemented**: at that point `ads`
    belongs in `EDITOR_WRITERS`, and routing it to `editor` should succeed.
    """
    from apex_ads.compile_.editor_export import EDITOR_WRITERS

    assert "ads" not in EDITOR_WRITERS, (
        "RSA Editor export now exists — invert this test to expect a successful export"
    )

    schema = config.editor_schema
    rerouted = {**schema.inventory, "ads": "editor"}
    broken = verified(config).model_copy(
        update={"editor_schema": schema.model_copy(update={"inventory": rerouted})}
    )

    result = build(launchable, broken, fixture_rules, tmp_path)

    assert result.outcome is Outcome.FAILED
    assert result.files == []
    misrouted = [f for f in result.findings if f.rule_id == "EXP-002"]
    assert misrouted, "a destination with no handler must block"
    assert "no Editor writer exists" in misrouted[0].message
    assert "ads" in misrouted[0].entity or "ads" in misrouted[0].message


def test_a_manual_destination_without_a_renderer_blocks_the_build(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """The mirror case: routed to manual_steps, but nothing writes it out."""
    schema = config.editor_schema
    rerouted = {**schema.inventory, "keywords": "manual_steps"}
    broken = verified(config).model_copy(
        update={"editor_schema": schema.model_copy(update={"inventory": rerouted})}
    )

    result = build(launchable, broken, fixture_rules, tmp_path)

    assert result.outcome is Outcome.FAILED
    misrouted = [f for f in result.findings if f.rule_id == "EXP-002"]
    assert any("no renderer" in f.message for f in misrouted), [f.message for f in misrouted]


def test_editor_writers_match_what_write_all_emits(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """`EDITOR_WRITERS` must describe reality, or the guard is checking a fiction."""
    from apex_ads.compile_.editor_export import EDITOR_WRITERS

    result = build(launchable, verified(config), fixture_rules, tmp_path)
    schema = config.editor_schema

    expected_files = {
        schema.entities[name].file for name in EDITOR_WRITERS if name in schema.entities
    } | {
        artifact.file
        for key, artifact in schema.negative_artifacts.items()
        if key
        in {"account_negatives", "shared_negative_lists", "campaign_negatives", "adgroup_negatives"}
    }
    assert {file.path.name for file in result.files} == expected_files


def test_every_declared_handler_covers_a_real_collection(config: Config) -> None:
    """Neither capability set may name a record type the compiler does not produce."""
    from apex_ads.compile_.editor_export import EDITOR_WRITERS
    from apex_ads.compile_.manual_steps import MANUAL_RENDERERS
    from apex_ads.compile_.transform import CompiledAccount

    produced = set(CompiledAccount().collections())
    assert produced >= EDITOR_WRITERS, sorted(EDITOR_WRITERS - produced)
    assert produced >= MANUAL_RENDERERS, sorted(MANUAL_RENDERERS - produced)
    assert produced == EDITOR_WRITERS | MANUAL_RENDERERS, "some record type has no handler"


# --------------------------------------------------- verification needs provenance


def test_verified_true_without_provenance_will_not_load(config: Config) -> None:
    """Prose asking a human to fill these in is not enforcement.

    `verified: true` with four nulls used to load happily and produce READY builds, which
    defeats the point of recording provenance at all.
    """
    from apex_ads.models.config import EditorSchema

    payload = {**config.editor_schema.model_dump(), "verified": True}
    with pytest.raises(ValueError, match="requires complete verified_against provenance"):
        EditorSchema.model_validate(payload)


def test_verified_true_rejects_a_malformed_hash(config: Config) -> None:
    from apex_ads.models.config import EditorSchema

    payload = {
        **config.editor_schema.model_dump(),
        "verified": True,
        "verified_against": {
            "export_date": "2026-08-20",
            "editor_version": "Google Ads Editor 2.9",
            "source_sha256": "not-a-hash",
            "reconciled_by": "Gaurav",
        },
    }
    with pytest.raises(ValueError, match="64 hex characters"):
        EditorSchema.model_validate(payload)


def test_manual_steps_states_verification_provenance_when_verified(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    """A verified build must not also announce that its column names are unverified."""
    result = build(launchable, verified(config), fixture_rules, tmp_path)
    text = (result.directory / "MANUAL_STEPS.md").read_text(encoding="utf-8")

    assert "unverified" not in text.casefold()
    assert "Editor column names verified" in text
    assert "2026-08-20" in text


def test_manual_steps_warns_when_the_schema_is_unverified(
    launchable: WorkbookBundle, fixture_rules: Rules, config: Config, tmp_path: Path
) -> None:
    result = build(launchable, config, fixture_rules, tmp_path)
    text = (result.directory / "MANUAL_STEPS.md").read_text(encoding="utf-8")
    assert "unverified" in text.casefold()
    assert "Editor column names verified" not in text
