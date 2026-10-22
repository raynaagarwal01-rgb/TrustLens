"""
link_checker.py — TrustLens link / phishing checker (Track 4)

Offline checks (instant, always run):
  - lookalike / typosquatted domains (amaz0n.in, hdfcbank-secure.com)
  - brand names used on a domain the brand doesn't own (sbi-kyc-update.xyz)
  - raw IP addresses, punycode (xn--), '@' tricks, too many subdomains
  - risky TLDs, phishing keywords, no HTTPS, link shorteners

Online checks (optional, each fails gracefully, results cached):
  - domain age via RDAP (no API key needed)
  - Google Safe Browsing   (env GSB_API_KEY)
  - VirusTotal URL report  (env VT_API_KEY)
  - shortened-link expansion (follows redirects of known shorteners only)

Usage:
    from link_checker import check_url
    report = check_url("http://sbi-kyc-update.xyz/login")
    report = check_url(url, online=False)   # offline only, instant
"""

import base64
import difflib
import ipaddress
import json
import os
import re
import threading
from datetime import datetime, timezone
from urllib.parse import urlsplit

from collections import namedtuple

# Minimal domain splitter (no external dependency). Covers the multi-part
# endings you'll meet in Indian links; everything else is treated as a
# single-label ending like .com or .xyz.
MULTI_PART_SUFFIXES = {
    "co.in", "ac.in", "gov.in", "nic.in", "org.in", "net.in", "edu.in", "res.in",
    "bank.in", "firm.in", "gen.in", "ind.in", "mil.in",
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "co.nz", "com.sg", "com.br", "co.jp",
}

Extracted = namedtuple("Extracted", "subdomain domain suffix")


def _extract(host: str) -> Extracted:
    host = host.lower().strip(".")
    labels = host.split(".")
    if len(labels) < 2 or host.replace(".", "").isdigit() or ":" in host:
        return Extracted("", host, "")
    n = 2 if ".".join(labels[-2:]) in MULTI_PART_SUFFIXES and len(labels) >= 3 else 1
    suffix = ".".join(labels[-n:])
    return Extracted(".".join(labels[:-n - 1]), labels[-n - 1], suffix)

TIMEOUT = 4  # seconds per online call — keeps the demo snappy
CACHE_FILE = os.getenv("TRUSTLENS_CACHE", ".trustlens_cache.json")

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

# brand keyword -> registered domains that brand actually owns
OFFICIAL_DOMAINS = {
    "sbi": ["sbi.co.in", "onlinesbi.sbi", "sbi.bank.in", "sbicard.com"],
    "hdfc": ["hdfcbank.com", "hdfc.bank.in", "hdfc.com"],
    "icici": ["icicibank.com", "icici.bank.in"],
    "axis": ["axisbank.com", "axis.bank.in"],
    "kotak": ["kotak.com", "kotak.bank.in"],
    "paytm": ["paytm.com", "paytmbank.com"],
    "phonepe": ["phonepe.com"],
    "gpay": ["pay.google.com", "google.com"],
    "npci": ["npci.org.in"],
    "amazon": ["amazon.in", "amazon.com", "amazonaws.com", "amazon.jobs"],
    "flipkart": ["flipkart.com"],
    "irctc": ["irctc.co.in"],
    "uidai": ["uidai.gov.in"],
    "aadhaar": ["uidai.gov.in"],
    "incometax": ["incometax.gov.in"],
    "indiapost": ["indiapost.gov.in"],
    "vit": ["vit.ac.in", "vitbhopal.ac.in", "vitap.ac.in"],
    "internshala": ["internshala.com"],
    "naukri": ["naukri.com"],
    "linkedin": ["linkedin.com", "lnkd.in"],
    "microsoft": ["microsoft.com", "live.com", "office.com"],
    "google": ["google.com", "google.co.in", "goo.gl"],
    "whatsapp": ["whatsapp.com", "wa.me"],
    "instagram": ["instagram.com"],
    "fedex": ["fedex.com"],
}

SHORTENERS = {"bit.ly", "tinyurl.com", "t.ly", "cutt.ly", "rb.gy", "is.gd", "shorturl.at",
              "goo.gl", "t.co", "ow.ly", "tiny.cc", "s.id", "v.gd"}

RISKY_TLDS = {"xyz", "top", "click", "link", "online", "site", "live", "icu", "buzz", "rest",
              "shop", "store", "monster", "cfd", "sbs", "lat", "work", "support", "info", "loan"}

PHISH_WORDS = ["login", "signin", "verify", "verification", "kyc", "update", "secure", "account",
               "wallet", "reward", "refund", "bonus", "claim", "unlock", "suspend", "otp", "bank"]

HOMOGLYPHS = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "@": "a"})

WEIGHTS = {"high": 35, "medium": 15, "low": 5}

# Minimum score when a finding fires, regardless of what else was found
SCORE_FLOORS = {
    "Google Safe Browsing match": 90,
    "Flagged by security vendors": 90,
    "Brand impersonation": 70,
    "Look-alike domain": 70,
    "Disguised characters (punycode)": 70,
    "'@' trick in link": 70,
    "Brand-new domain": 50,
    "IP address instead of domain": 50,
    "Shortened link": 30,  # destination unknown until expanded
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalise(url: str) -> str:
    url = url.strip().strip("<>\"'").rstrip(".,)")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "http://" + url if not url.lower().startswith("www.") else "http://" + url
    return url


def registered_domain(host: str) -> str:
    ext = _extract(host)
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain


def _finding(check, severity, detail):
    return {"check": check, "severity": severity, "detail": detail}


def _verdict_for(score: int) -> str:
    return "malicious" if score >= 65 else "suspicious" if score >= 30 else "likely_safe"


# Small JSON cache so repeated demo URLs never hit an API twice
_cache_lock = threading.Lock()


def _cache_get(key):
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f).get(key)
    except (OSError, ValueError):
        return None


def _cache_set(key, value):
    with _cache_lock:
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        data[key] = value
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1)
        except OSError:
            pass


def _cached(name):
    """Decorator: cache an online lookup's result by (check name, argument)."""
    def wrap(fn):
        def inner(arg):
            key = f"{name}:{arg}"
            hit = _cache_get(key)
            if hit is not None:
                return hit
            result = fn(arg)
            if result.get("status") == "ok":  # only cache successful lookups
                _cache_set(key, result)
            return result
        return inner
    return wrap

# ---------------------------------------------------------------------------
# Offline checks
# ---------------------------------------------------------------------------

def offline_checks(url: str) -> list[dict]:
    findings = []
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    ext = _extract(host)
    reg = registered_domain(host)
    label = ext.domain.lower()
    full = url.lower()

    if not host:
        return [_finding("Unreadable link", "medium", "Could not find a domain in this link")]

    # Raw IP address instead of a name
    try:
        ipaddress.ip_address(host)
        findings.append(_finding("IP address instead of domain", "high",
                                 f"Link points to a bare IP ({host}); real organisations use named websites"))
    except ValueError:
        pass

    if "xn--" in host:
        findings.append(_finding("Disguised characters (punycode)", "high",
                                 "Domain uses look-alike letters from other alphabets to imitate a real site"))

    if "@" in (parts.netloc or ""):
        findings.append(_finding("'@' trick in link", "high",
                                 "Everything before '@' is ignored by the browser; the real destination is after it"))

    if reg in SHORTENERS:
        findings.append(_finding("Shortened link", "medium",
                                 f"{reg} hides the real destination"))

    if ext.suffix.split(".")[-1] in RISKY_TLDS:
        findings.append(_finding("Risky domain ending", "medium",
                                 f".{ext.suffix} domains are cheap and widely used for scam sites"))

    if parts.scheme == "http":
        findings.append(_finding("No HTTPS", "low", "Connection is not encrypted"))

    sub = ext.subdomain
    if sub and sub.count(".") >= 2:
        findings.append(_finding("Too many subdomains", "medium",
                                 f"'{host}' stacks subdomains to look official"))

    # Brand impersonation and typosquatting
    owned = {d for doms in OFFICIAL_DOMAINS.values() for d in doms}
    is_official = reg in owned or any(host.endswith("." + d) or host == d for d in owned)
    if not is_official:
        tokens = re.split(r"[.\-_/]", host)
        for brand, doms in OFFICIAL_DOMAINS.items():
            names = {brand} | {_extract(d).domain for d in doms if len(_extract(d).domain) >= 4}
            if any(n in tokens or (len(n) >= 5 and n in host) for n in names):
                findings.append(_finding("Brand impersonation", "high",
                                         f"Uses the name '{brand}' but isn't {brand}'s real site ({doms[0]})"))
                break
        else:
            for brand, doms in OFFICIAL_DOMAINS.items():
                for d in doms:
                    official_label = _extract(d).domain
                    if len(official_label) < 4 or official_label == label:
                        continue
                    ratio = difflib.SequenceMatcher(None, label, official_label).ratio()
                    if label.translate(HOMOGLYPHS) == official_label or ratio >= 0.85:
                        findings.append(_finding("Look-alike domain", "high",
                                                 f"'{reg}' imitates '{d}'"))
                        break
                else:
                    continue
                break

    words = [w for w in PHISH_WORDS if re.search(rf"(?<![a-z]){w}", full)]
    if words and not is_official:
        findings.append(_finding("Phishing keywords", "medium" if len(words) > 1 else "low",
                                 "Link contains: " + ", ".join(words[:4])))

    if len(url) > 100:
        findings.append(_finding("Very long link", "low", "Long links are often used to hide the real domain"))

    return findings

# ---------------------------------------------------------------------------
# Online checks (all optional)
# ---------------------------------------------------------------------------

def _requests():
    import requests  # imported lazily so offline mode needs no network libs
    return requests


@_cached("rdap")
def domain_age(domain: str) -> dict:
    try:
        r = _requests().get(f"https://rdap.org/domain/{domain}", timeout=TIMEOUT)
        if r.status_code != 200:
            return {"status": "unavailable", "detail": f"RDAP HTTP {r.status_code}"}
        for ev in r.json().get("events", []):
            if ev.get("eventAction") == "registration":
                created = datetime.fromisoformat(ev["eventDate"].replace("Z", "+00:00"))
                days = (datetime.now(timezone.utc) - created).days
                return {"status": "ok", "created": created.date().isoformat(), "age_days": days}
        return {"status": "unavailable", "detail": "No registration date published"}
    except Exception as e:
        return {"status": "error", "detail": type(e).__name__}


@_cached("gsb")
def safe_browsing(url: str) -> dict:
    key = os.getenv("GSB_API_KEY")
    if not key:
        return {"status": "skipped", "detail": "GSB_API_KEY not set"}
    body = {
        "client": {"clientId": "trustlens", "clientVersion": "0.1"},
        "threatInfo": {
            "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE",
                            "POTENTIALLY_HARMFUL_APPLICATION"],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}],
        },
    }
    try:
        r = _requests().post(f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={key}",
                             json=body, timeout=TIMEOUT)
        if r.status_code != 200:
            return {"status": "error", "detail": f"HTTP {r.status_code}"}
        matches = r.json().get("matches", [])
        return {"status": "ok", "flagged": bool(matches),
                "threats": sorted({m.get("threatType") for m in matches})}
    except Exception as e:
        return {"status": "error", "detail": type(e).__name__}


@_cached("vt")
def virustotal(url: str) -> dict:
    key = os.getenv("VT_API_KEY")
    if not key:
        return {"status": "skipped", "detail": "VT_API_KEY not set"}
    url_id = base64.urlsafe_b64encode(url.encode()).decode().strip("=")
    try:
        r = _requests().get(f"https://www.virustotal.com/api/v3/urls/{url_id}",
                            headers={"x-apikey": key}, timeout=TIMEOUT)
        if r.status_code == 404:
            return {"status": "ok", "known": False}
        if r.status_code == 429:
            return {"status": "error", "detail": "rate limited"}
        if r.status_code != 200:
            return {"status": "error", "detail": f"HTTP {r.status_code}"}
        stats = r.json()["data"]["attributes"]["last_analysis_stats"]
        return {"status": "ok", "known": True, "malicious": stats.get("malicious", 0),
                "suspicious": stats.get("suspicious", 0), "harmless": stats.get("harmless", 0)}
    except Exception as e:
        return {"status": "error", "detail": type(e).__name__}


@_cached("expand")
def expand_short_link(url: str) -> dict:
    try:
        r = _requests().get(url, allow_redirects=True, timeout=TIMEOUT, stream=True,
                            headers={"User-Agent": "Mozilla/5.0 TrustLens"})
        final = r.url
        r.close()
        return {"status": "ok", "final_url": final}
    except Exception as e:
        return {"status": "error", "detail": type(e).__name__}


def online_checks(url: str, findings: list[dict]) -> dict:
    host = (urlsplit(url).hostname or "").lower()
    reg = registered_domain(host)
    results = {}

    if reg in SHORTENERS:
        exp = expand_short_link(url)
        results["expanded"] = exp
        if exp.get("status") == "ok" and exp["final_url"] != url:
            findings.append(_finding("Real destination", "low", f"Short link leads to {exp['final_url']}"))
            inner = offline_checks(exp["final_url"])
            findings.extend(inner)
            url = exp["final_url"]
            reg = registered_domain(urlsplit(url).hostname or "")

    age = domain_age(reg)
    results["domain_age"] = age
    if age.get("status") == "ok":
        days = age["age_days"]
        if days < 30:
            findings.append(_finding("Brand-new domain", "high", f"Registered only {days} days ago ({age['created']})"))
        elif days < 180:
            findings.append(_finding("Young domain", "medium", f"Registered {days} days ago ({age['created']})"))

    gsb = safe_browsing(url)
    results["safe_browsing"] = gsb
    if gsb.get("flagged"):
        findings.append(_finding("Google Safe Browsing match", "high",
                                 "Listed by Google as: " + ", ".join(gsb["threats"])))

    vt = virustotal(url)
    results["virustotal"] = vt
    if vt.get("malicious", 0) >= 2:
        findings.append(_finding("Flagged by security vendors", "high",
                                 f"{vt['malicious']} VirusTotal engines mark this as malicious"))
    elif vt.get("malicious", 0) == 1 or vt.get("suspicious", 0) >= 2:
        findings.append(_finding("Some vendors suspicious", "medium",
                                 f"VirusTotal: {vt.get('malicious', 0)} malicious, {vt.get('suspicious', 0)} suspicious"))
    return results

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_url(url: str, online: bool = True) -> dict:
    url = normalise(url)
    host = (urlsplit(url).hostname or "").lower()
    findings = offline_checks(url)
    online_results = online_checks(url, findings) if online else {}

    # de-duplicate findings by check name, keeping the most severe
    order = {"high": 3, "medium": 2, "low": 1}
    best = {}
    for f in findings:
        if f["check"] not in best or order[f["severity"]] > order[best[f["check"]]["severity"]]:
            best[f["check"]] = f
    findings = sorted(best.values(), key=lambda f: -order[f["severity"]])

    score = min(100, sum(WEIGHTS[f["severity"]] for f in findings))
    for f in findings:  # some findings are serious enough on their own
        score = max(score, SCORE_FLOORS.get(f["check"], 0))

    return {
        "url": url,
        "domain": registered_domain(host),
        "verdict": _verdict_for(score),
        "risk_score": score,
        "findings": findings,
        "online": online_results,
    }


def check_urls(urls: list[str], online: bool = True) -> list[dict]:
    return [check_url(u, online=online) for u in dict.fromkeys(urls)][:5]


DEMO_URLS = [
    "bit.ly/amz-intern-offer",
    "sbi-kyc-update.xyz",
    "http://paytm-kyc.verify-login.top/update",
    "https://amaz0n.in/jobs/apply",
    "http://192.168.4.20/hdfc/login",
    "https://www.vit.ac.in",
    "https://www.amazon.in/gp/help",
]

if __name__ == "__main__":
    online = os.getenv("TRUSTLENS_OFFLINE") != "1"
    for u in DEMO_URLS:
        r = check_url(u, online=online)
        print(f"\n{r['verdict'].upper():12} {r['risk_score']:>3}  {r['url']}")
        for f in r["findings"]:
            print(f"   [{f['severity']}] {f['check']}: {f['detail']}")
