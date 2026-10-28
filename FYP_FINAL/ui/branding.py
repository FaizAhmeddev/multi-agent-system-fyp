"""Local, original Office Automation Pro artwork shared by every UI surface."""
from base64 import b64encode
from functools import lru_cache
from pathlib import Path

BRAND_ASSETS = Path(__file__).parent / "assets" / "brand"
FAVICON = BRAND_ASSETS / "favicon.png"


@lru_cache(maxsize=1)
def logo_html() -> str:
    images = []
    for mode, filename in (("light", "office-automation-logo.png"),
                           ("dark", "office-automation-logo-dark.png")):
        encoded = b64encode((BRAND_ASSETS / filename).read_bytes()).decode("ascii")
        images.append(f'<img class="brand-{mode}" src="data:image/png;base64,{encoded}" '
            'alt="Office Automation Pro" width="1987" height="310" '
            'decoding="async" draggable="false">')
    return '<span class="office-brand-artwork">' + ''.join(images) + '</span>'
