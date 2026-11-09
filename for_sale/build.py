"""Build the For Sale page from inventory.toml.

TCGplayer items get their name, set, image and market price from tcgcsv.com,
a free daily mirror of TCGplayer's catalog and prices. Which TCGplayer
category and set each product belongs to is cached in tcgplayer_lookup.json,
so after the first build only the needed sets are fetched.

The Venmo QR code is generated once into venmo-qr.svg and committed, so the
normal build needs only the standard library. Regenerating it (after changing
the Venmo handle) needs segno:

    uv run --with segno python3 scripts/build.py
"""

import json
import re
import shutil
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
INVENTORY = HERE / "inventory.toml"
TEMPLATE = HERE / "template.html"
LOOKUP = HERE / "tcgplayer_lookup.json"
QR = HERE / "venmo-qr.svg"
OUT_NAME = "for-sale.html"
IMAGES_DIR = "for-sale-images"

TCGCSV = "https://tcgcsv.com"
# Searched in order for products not yet in the lookup cache:
# Lorcana TCG, Playmats, Supplies, TCGplayer Supplies.
CATEGORIES = [71, 35, 14, 82]
CDN = "https://tcgplayer-cdn.tcgplayer.com/product/{id}_in_{size}x{size}.jpg"


def fetch(path: str):
    req = urllib.request.Request(f"{TCGCSV}/{path}", headers={"User-Agent": "static-lorcana-for-sale"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            body = res.read().decode()
    except urllib.error.URLError as err:
        if "CERTIFICATE_VERIFY_FAILED" in str(err.reason):
            raise SystemExit(
                "This Python can't verify HTTPS certificates. On a python.org install on macOS, run\n"
                "  open '/Applications/Python 3.14/Install Certificates.command'\n"
                "(matching your version), or build with `uv run python3 scripts/build.py`.")
        raise
    return json.loads(body)["results"] if path.endswith(("groups", "products", "prices")) else body


def product_id(ref) -> int:
    if isinstance(ref, int):
        return ref
    m = re.search(r"/product/(\d+)", ref) or re.fullmatch(r"\s*(\d+)\s*", ref)
    if not m:
        raise SystemExit(f"Can't find a TCGplayer product ID in {ref!r}")
    return int(m.group(1))


def locate(ids: set[int]) -> dict[str, dict]:
    """Map product ID -> {categoryId, groupId}, searching TCGCSV for new IDs."""
    lookup = json.loads(LOOKUP.read_text()) if LOOKUP.exists() else {}
    missing = {i for i in ids if str(i) not in lookup}
    for cat in CATEGORIES:
        if not missing:
            break
        for group in fetch(f"tcgplayer/{cat}/groups"):
            for p in fetch(f"tcgplayer/{cat}/{group['groupId']}/products"):
                if p["productId"] in missing:
                    lookup[str(p["productId"])] = {"categoryId": cat, "groupId": group["groupId"]}
                    missing.discard(p["productId"])
            if not missing:
                break
    if missing:
        raise SystemExit(f"TCGplayer product(s) not found on tcgcsv.com: {sorted(missing)}")
    LOOKUP.write_text(json.dumps(dict(sorted(lookup.items())), indent=2) + "\n")
    return lookup


def kind_of(product: dict) -> str:
    if product["categoryId"] == 35:
        return "Playmat"
    if product["categoryId"] == 71:
        has_rarity = any(e["name"] == "Rarity" for e in product.get("extendedData", []))
        return "Card" if has_rarity else "Sealed"
    return "Accessory"


def display_name(name: str) -> str:
    return re.sub(r"^Disney Lorcana:\s*", "", name)


def asking_price(market: float, pricing: dict) -> float:
    price = market * pricing.get("percent_of_market", 100) / 100
    step = pricing.get("round_to", 1)
    return round(round(price / step) * step, 2) if step else round(price, 2)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def venmo_qr(handle: str) -> str:
    """Inline SVG QR code for the Venmo profile, regenerated when the handle changes."""
    if not handle:
        return ""
    url = f"https://venmo.com/u/{handle}"
    marker = f"<!-- {url} -->"
    if QR.exists() and QR.read_text().startswith(marker):
        return QR.read_text().split("\n", 1)[1]
    try:
        import segno
    except ImportError:
        print(f"Note: venmo-qr.svg is missing or out of date. Run with segno to regenerate it:\n"
              f"  uv run --with segno python3 scripts/build.py")
        return ""
    svg = segno.make(url, error="m").svg_inline(scale=1, border=2, dark="#008CFF", light="#ffffff", omitsize=True)
    QR.write_text(f"{marker}\n{svg}\n")
    return svg


def build(out_dir: Path) -> Path:
    """Write the page into out_dir and return its path."""
    inv = tomllib.loads(INVENTORY.read_text())
    seller, pricing = inv.get("seller", {}), inv.get("pricing", {})
    entries = [i for i in inv.get("item", []) if i.get("qty", 1) > 0]

    tcg_ids = {product_id(i["tcgplayer"]) for i in entries if "tcgplayer" in i}
    lookup = locate(tcg_ids) if tcg_ids else {}
    products, prices, groups = {}, {}, {}
    for cat, group in sorted({(v["categoryId"], v["groupId"]) for k, v in lookup.items() if int(k) in tcg_ids}):
        for p in fetch(f"tcgplayer/{cat}/{group}/products"):
            products[p["productId"]] = p
        for p in fetch(f"tcgplayer/{cat}/{group}/prices"):
            prices.setdefault(p["productId"], {})[p["subTypeName"]] = p
        if cat not in groups:
            groups[cat] = {g["groupId"]: g["name"] for g in fetch(f"tcgplayer/{cat}/groups")}

    items, seen = [], set()
    for entry in entries:
        item = {
            "qty": entry.get("qty", 1),
            "condition": entry.get("condition", ""),
            "note": entry.get("note", ""),
            "printing": entry.get("printing", ""),
        }
        if "tcgplayer" in entry:
            pid = product_id(entry["tcgplayer"])
            p = products[pid]
            by_printing = prices.get(pid, {})
            printing = entry.get("printing") or ("Normal" if "Normal" in by_printing else next(iter(by_printing), ""))
            if by_printing and printing not in by_printing:
                raise SystemExit(f"{p['name']}: no {printing!r} price on TCGplayer (has {', '.join(by_printing)})")
            quote = by_printing.get(printing, {})
            market = quote.get("marketPrice") or quote.get("midPrice")
            if "price" not in entry and market is None:
                raise SystemExit(f"{p['name']} has no TCGplayer market price; set `price` for it in inventory.toml")
            item.update({
                "id": f"tcg{pid}",
                "name": display_name(p["name"]),
                "set": groups[p["categoryId"]].get(p["groupId"], ""),
                "kind": entry.get("kind") or kind_of(p),
                "price": entry["price"] if "price" in entry else asking_price(market, pricing),
                "market": market,
                "image": CDN.format(id=pid, size=400),
                "imageLarge": CDN.format(id=pid, size=1000),
                "url": p["url"],
                "printing": printing if len(by_printing) > 1 else "",
            })
        else:
            if "name" not in entry or "price" not in entry:
                raise SystemExit(f"Items without a TCGplayer link need a name and a price: {entry}")
            image = entry.get("image", "")
            if image and not re.match(r"https?://", image):
                src = HERE / image
                (out_dir / IMAGES_DIR).mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, out_dir / IMAGES_DIR / src.name)
                image = f"{IMAGES_DIR}/{src.name}"
            item.update({
                "id": slug(entry["name"]), "name": entry["name"], "set": entry.get("set", ""),
                "kind": entry.get("kind", "Accessory"), "price": entry["price"], "market": None,
                "image": image, "imageLarge": image, "url": entry.get("url", ""),
            })
        for extra in (item["printing"], item["condition"]):
            if extra:
                item["id"] += "-" + slug(extra)
        base, n = item["id"], 2
        while item["id"] in seen:
            item["id"], n = f"{base}-{n}", n + 1
        seen.add(item["id"])
        items.append(item)

    data = {
        "seller": {k: seller.get(k, "") for k in ("discord", "discord_user_id", "venmo", "location")},
        "items": items,
        "pricesAsOf": fetch("last-updated.txt").strip() if tcg_ids else "",
        "builtAt": datetime.now(timezone.utc).isoformat(timespec="minutes"),
    }
    page = (TEMPLATE.read_text()
            .replace("__INVENTORY_JSON__", json.dumps(data).replace("<", "\\u003c"))
            .replace("<!--VENMO_QR-->", venmo_qr(seller.get("venmo", ""))))
    out = out_dir / OUT_NAME
    out.write_text(page, encoding="utf-8")
    print(f"For Sale: {len(items)} item(s)")
    return out
