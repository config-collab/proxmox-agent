"""
CVE lookup via NIST NVD API v2.
Returns recent vulnerabilities for a given package or keyword.
Rate-limited: 5 req/30s without API key, 50/30s with.
"""
import json
import urllib.request
import urllib.parse
from pathlib import Path
import os

NVD_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_KEY = os.environ.get("NVD_API_KEY", "")   # optional — set for higher rate limit


def search(keyword: str, top_k: int = 5, severity_min: str = "") -> list[dict]:
    """
    Search NVD for CVEs matching keyword.
    Returns list of {id, description, score, severity, published, url}.
    severity_min: "" = all, "MEDIUM", "HIGH", "CRITICAL"
    """
    params = {
        "keywordSearch": keyword,
        "resultsPerPage": min(top_k * 3, 20),   # fetch extra; filter locally
    }
    if NVD_KEY:
        params["apiKey"] = NVD_KEY

    url = f"{NVD_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "proxmox-agent/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        return [{"id": "error", "description": str(exc), "score": 0, "severity": "", "published": "", "url": ""}]

    results = []
    for item in data.get("vulnerabilities", []):
        cve    = item.get("cve", {})
        cve_id = cve.get("id", "?")
        desc   = next((d["value"] for d in cve.get("descriptions", []) if d.get("lang") == "en"), "")

        # Extract CVSS score
        score, sev = 0.0, ""
        for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            metric = cve.get("metrics", {}).get(key, [])
            if metric:
                cvss_data = metric[0].get("cvssData", {})
                score = float(cvss_data.get("baseScore", 0))
                sev   = cvss_data.get("baseSeverity", "")
                break

        if severity_min and sev not in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            continue
        sev_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "": 0}
        min_rank = sev_rank.get(severity_min.upper(), 0)
        if sev_rank.get(sev, 0) < min_rank:
            continue

        published = cve.get("published", "")[:10]
        url       = f"https://nvd.nist.gov/vuln/detail/{cve_id}"

        results.append({
            "id":          cve_id,
            "description": desc[:300],
            "score":       score,
            "severity":    sev,
            "published":   published,
            "url":         url,
        })
        if len(results) >= top_k:
            break

    return results


def search_formatted(keyword: str, top_k: int = 5) -> str:
    """Return formatted CVE results for LLM consumption."""
    results = search(keyword, top_k)
    if not results or results[0].get("id") == "error":
        err = results[0]["description"] if results else "no results"
        return f"CVE lookup failed for '{keyword}': {err}"

    lines = [f"CVEs matching '{keyword}' (NVD):"]
    for r in results:
        sev_badge = f"[{r['severity']}]" if r["severity"] else ""
        lines.append(f"\n{r['id']} {sev_badge} CVSS {r['score']} ({r['published']})")
        lines.append(f"  {r['description']}")
        lines.append(f"  {r['url']}")
    return "\n".join(lines)
