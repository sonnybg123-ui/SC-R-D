"""Fail-closed checks for declared local research data provenance and coverage."""
from __future__ import annotations

from .research import canonical, digest, fields, instant


def validate_manifest(manifest: dict, data: dict, grid: list, hashes: dict) -> dict:
    fields(manifest, {"schema_version", "datasets"}, "data manifest")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("unsupported data-manifest schema_version")
    if not isinstance(manifest["datasets"], dict) or set(manifest["datasets"]) != set(data):
        raise ValueError("manifest symbols must exactly match the portfolio dataset universe")
    expected_fields = {"kind", "source", "license", "currency", "normalized_timezone", "timestamp_role",
                       "bar_seconds", "price_adjustment", "expected_sha256", "expected_rows",
                       "expected_start", "expected_end", "allowed_gaps"}
    validated, currencies, adjustments, kinds = {}, set(), set(), set()
    for symbol in sorted(data):
        item = manifest["datasets"][symbol]
        fields(item, expected_fields, f"manifest for {symbol}")
        for key in ("source", "license", "currency"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(f"{symbol}: nonempty {key} declaration required")
        if item["kind"] not in {"synthetic", "market"}:
            raise ValueError(f"{symbol}: kind must be synthetic or market")
        if item["normalized_timezone"] != "UTC" or item["timestamp_role"] != "open":
            raise ValueError(f"{symbol}: normalized UTC timestamps labelled at candle open required")
        if item["price_adjustment"] not in {"raw", "split_adjusted", "total_return_adjusted", "synthetic"}:
            raise ValueError(f"{symbol}: unsupported price_adjustment")
        if (item["kind"] == "synthetic") != (item["price_adjustment"] == "synthetic"):
            raise ValueError(f"{symbol}: synthetic kind and adjustment declarations must agree")
        for key in ("bar_seconds", "expected_rows"):
            if type(item[key]) is not int or item[key] < 1:
                raise ValueError(f"{symbol}: {key} must be a positive integer")
        sha = item["expected_sha256"]
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError(f"{symbol}: expected_sha256 must be lowercase SHA-256")
        if hashes[symbol] != sha:
            raise ValueError(f"{symbol}: dataset fingerprint mismatch")
        if len(data[symbol]) != item["expected_rows"] or len(grid) != len(data[symbol]):
            raise ValueError(f"{symbol}: dataset row-count mismatch")
        if instant(item["expected_start"]) != grid[0] or instant(item["expected_end"]) != grid[-1]:
            raise ValueError(f"{symbol}: dataset coverage mismatch")
        if not isinstance(item["allowed_gaps"], list):
            raise ValueError(f"{symbol}: allowed_gaps must be a list")
        allowed = set()
        for gap in item["allowed_gaps"]:
            fields(gap, {"after", "before"}, "declared gap")
            pair = (instant(gap["after"]), instant(gap["before"]))
            if pair in allowed or pair[0] >= pair[1]:
                raise ValueError(f"{symbol}: invalid or duplicate declared gap")
            allowed.add(pair)
        used = set()
        for before, after in zip(grid, grid[1:]):
            delta = (after - before).total_seconds()
            if delta == item["bar_seconds"]:
                continue
            if delta <= item["bar_seconds"] or delta % item["bar_seconds"] != 0:
                raise ValueError(f"{symbol}: irregular candle spacing")
            if (before, after) not in allowed:
                raise ValueError(f"{symbol}: undeclared missing-bar interval")
            used.add((before, after))
        if allowed != used:
            raise ValueError(f"{symbol}: unused or inaccurate declared gap")
        warnings = ["Source and licensing are declarations, not independently verified endorsements."]
        if item["kind"] == "synthetic":
            warnings.append("Synthetic fixture: no empirical market-edge evidence.")
        if used:
            warnings.append(f"{len(used)} explicitly declared gaps accepted; no exchange-calendar inference.")
        validated[symbol] = {"declaration": item, "actual_sha256": hashes[symbol], "rows": len(data[symbol]),
                             "first_open": grid[0].isoformat(), "last_open": grid[-1].isoformat(),
                             "declared_gaps": len(used), "warnings": warnings}
        currencies.add(item["currency"])
        adjustments.add(item["price_adjustment"])
        kinds.add(item["kind"])
    if len(currencies) != 1 or len(adjustments) != 1 or len(kinds) != 1:
        raise ValueError("portfolio datasets must share currency, adjustment policy and data kind")
    return {"passed": True, "manifest_sha256": digest(canonical(manifest).encode()), "datasets": validated}
