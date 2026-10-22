"""Run with: python tests/test_event.py   (or pytest). No API key, network or VTOP needed."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import event_check as ec  # noqa: E402

NOWEB = {"status": "ok", "found": "no", "official_urls": [], "registration_domain": "", "fee_info": "", "summary": ""}
SKIP = {"status": "skipped"}


def ev(**k):
    base = {"is_event_promotion": True, "event_name": "", "organizer": "", "claimed_partners": [],
            "event_type": "hackathon", "dates": "", "mode": "", "venue": "", "fee": "", "payment_details": [],
            "registration_links": [], "contacts": [], "prizes": "", "deadline_pressure": "", "visible_text": ""}
    return {**base, **k}


FAKE = ev(event_name="CodeStorm National Hackathon 2026", organizer="CodeStorm Tech Community", fee="₹499 per team",
          payment_details=["UPI: codestorm.demo@okaxis"], registration_links=["codestorm-hackathon-reg.xyz"],
          contacts=["WhatsApp +91 90000 00000", "codestorm.team@gmail.com"],
          deadline_pressure="LAST DATE TODAY! Only 50 seats left", visible_text="Pay via UPI: codestorm.demo@okaxis")


def test_unknown_paid_event_with_upi_is_likely_scam():
    r = ec.assess(FAKE, NOWEB, SKIP, online_links=False)
    flags = {f["flag"] for f in r["red_flags"]}
    assert r["verdict"] == "likely_scam"
    assert {"Fee paid to a UPI ID", "Urgency pressure", "Personal email for an organisation"} <= flags


def test_real_event_with_fake_link_is_impersonation():
    e = ev(event_name="Smart India Hackathon 2026", organizer="Ministry of Education", fee="₹250",
           registration_links=["sih-2026-registration.online"])
    web = {**NOWEB, "found": "yes", "official_urls": ["https://www.sih.gov.in/"], "registration_domain": "sih.gov.in",
           "fee_info": "Registration is free"}
    r = ec.assess(e, web, SKIP, online_links=False)
    flags = {f["flag"] for f in r["red_flags"]}
    assert r["verdict"] == "likely_scam"
    assert {"Link doesn't match the official event", "Official event is free"} <= flags


def test_event_listed_on_vtop_is_verified():
    e = ev(event_name="DevSprint 2026 Hackathon", organizer="Developers Club", registration_links=["https://vtop.vit.ac.in"])
    campus = {"status": "ok", "source": "saved VTOP snapshot", "events_listed": 2,
              "match": {"event_name": "DevSprint 2026 Hackathon", "club": "Developers Club"}}
    r = ec.assess(e, NOWEB, campus, online_links=False)
    assert r["verdict"] == "verified" and "VTOP" in r["reasons"][0]


def test_official_platform_listing_is_verified():
    e = ev(event_name="HackNova 2026", organizer="HackNova", registration_links=["https://hacknova.devfolio.co"])
    web = {**NOWEB, "found": "yes", "official_urls": ["https://hacknova.devfolio.co/"]}
    assert ec.assess(e, web, SKIP, online_links=False)["verdict"] == "verified"


def test_not_found_free_event_is_only_unverified():
    e = ev(event_name="Intro to Rust Workshop", organizer="Some Club", event_type="workshop")
    assert ec.assess(e, NOWEB, SKIP, online_links=False)["verdict"] == "unverified"


def test_vtop_events_from_cli_top():
    import vtop
    os.environ["CLITOP_PATH"] = f"{sys.executable} {ROOT / 'tests' / 'fake_clitop.py'}"
    old_dir, old_idle = vtop.SNAPSHOT_DIR, vtop.IDLE_PROMPT_SECONDS
    vtop.SNAPSHOT_DIR, vtop.IDLE_PROMPT_SECONDS = ROOT / "tests" / "_snap_events", 2
    try:
        r = ec.vtop_events(ev(event_name="DevSprint 2026 Hackathon"), live=True)
        assert r["status"] == "ok" and r["match"]["club"] == "Developers Club"
        assert ec.vtop_events(ev(event_name="CodeStorm National Hackathon"), live=False)["match"] is None
    finally:
        import shutil
        shutil.rmtree(vtop.SNAPSHOT_DIR, ignore_errors=True)
        vtop.SNAPSHOT_DIR, vtop.IDLE_PROMPT_SECONDS = old_dir, old_idle
        del os.environ["CLITOP_PATH"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
