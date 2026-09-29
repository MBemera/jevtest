"""Synthetic vault contents so a mission can start mid-workflow instead of at first run.

All names, IDs and plates below are invented. The records are written through DT's own
service layer, exactly as the interface would write them.
"""

from pathlib import Path

SEED_PASSPHRASE = "jev-synthetic-passphrase-2026"
PROFILES = ("none", "empty", "sample")


def seed_vault(folder, profile, passphrase=SEED_PASSPHRASE):
    if profile == "none":
        return {}
    from dt.application import AssessmentService
    from dt.directory import DirectoryEntry
    from dt.storage import Vault

    folder = Path(folder)
    if folder.exists() and any(folder.iterdir()):
        return {"vault": str(folder), "passphrase": passphrase, "records": "kept existing vault"}
    vault = Vault(folder, passphrase, create=True)
    created = []
    try:
        if profile == "sample":
            service = AssessmentService(vault)
            blank = service.create()
            created.append(("new blank assessment", blank.id))
            partial = service.create(
                organisation="Synthetic Haulage Pty Ltd", assessor="Alex Assessor",
                driver={"name": "Sam Synthetic", "internal_id": "D-0042", "licence_class": "HR",
                        "licence_expiry": "2028-06-30 / VERIF-0042"},
                vehicle={"fleet_id": "FLEET-07", "registration": "XQ12AB", "configuration": "Rigid truck",
                         "truck_make": "", "truck_model": ""},
                scope="Rigid truck local delivery", conditions="Dry, light traffic, suburban route",
                recording_authority="Policy DT-REC-01 notice 2026-09")
            for criterion in partial.criteria[:10]:
                service.mark(partial, criterion.id, "C", "Performed safely and independently (synthetic).")
            service.mark(partial, partial.criteria[10].id, "D", "Needed a prompt to check mirrors (synthetic).")
            created.append(("prepared and partly marked assessment", partial.id))
            ready = service.create(
                organisation="Synthetic Haulage Pty Ltd", assessor="Alex Assessor",
                driver={"name": "Riley Ready", "internal_id": "D-0099", "licence_class": "HC",
                        "licence_expiry": "2027-11-30 / VERIF-0099"},
                vehicle={"fleet_id": "FLEET-12", "registration": "ZZ99RD", "configuration": "Prime mover and semitrailer"},
                scope="Semitrailer linehaul", conditions="Night, wet, highway",
                recording_authority="Policy DT-REC-01 notice 2026-09",
                prerequisites={"licence_verified": True, "vehicle_suitable": True,
                               "scope_confirmed": True, "instrument_reviewed": True})
            for criterion in ready.criteria:
                if criterion.mandatory:
                    service.mark(ready, criterion.id, "C", "Observed meeting the standard (synthetic).")
            created.append(("fully marked assessment, ready to sign", ready.id))
            vault.save_directory(DirectoryEntry("driver", {"name": "Dana Directory", "internal_id": "D-0100",
                                                           "licence_class": "MC"}), actor="Alex Assessor")
    finally:
        vault.close()
    return {"vault": str(folder), "passphrase": passphrase,
            "records": [f"{label} ({record_id[:8]})" for label, record_id in created]}


def write_catalogue_fixtures(fixtures):
    """Catalogue files for the module builder's Import catalogue button."""
    fixtures = Path(fixtures)
    fixtures.mkdir(parents=True, exist_ok=True)
    target = fixtures / "catalogue-exported.json"
    if not target.exists():
        try:
            from dt.catalogue import export_catalogue, load_catalogue
            export_catalogue(load_catalogue(), target)
        except Exception as error:  # noqa: BLE001 - fixtures are best effort
            (fixtures / "catalogue-exported.error.txt").write_text(repr(error), encoding="utf-8")
    broken = fixtures / "catalogue-malformed.json"
    if not broken.exists():
        broken.write_text('{"modules": [ {"id": "BROKEN", "title": ', encoding="utf-8")
    wrong = fixtures / "catalogue-wrong-shape.json"
    if not wrong.exists():
        wrong.write_text('{"schema": "not-a-dt-catalogue", "modules": "should be a list"}', encoding="utf-8")
