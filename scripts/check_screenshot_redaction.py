"""Scan committed workshop screenshots for identifiers that must not be public.

The capture pipeline redacts the DOM before taking a screenshot, and asserts
that nothing sensitive survived. That assertion has been wrong three times:

- an allowlist missed a tenant admin UPN in a grid column nobody thought about
- `document.body.innerText` does not include `<input>` values, so a combobox
  holding a real resource name passed the check and appeared in the PNG
- the Azure portal renders blades in iframes, so a top-frame-only pass left
  the subscription ID visible

Each of those was caught by eye. This is the backstop that does not rely on
eyes: once the DOM is gone, the only way to read a PNG is to read the pixels.

Run it before publishing, not on every commit - it needs Tesseract installed
and takes a few seconds per image:

    winget install UB-Mannheim.TesseractOCR
    services/api/.venv/Scripts/python.exe scripts/check_screenshot_redaction.py

Deliberately fails when OCR is unavailable rather than skipping. A privacy
check that silently passes because its dependency is missing is worse than no
check at all - it produces a green result nobody should trust.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = REPO_ROOT / "workshop" / "images"
CONFIG_PATH = Path(__file__).resolve().parent / "portal_redact.config.json"
EXAMPLE_CONFIG_PATH = Path(__file__).resolve().parent / "portal_redact.config.example.json"

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

# Mean luminance, 0-255. Portal chrome is either near-white or near-black, so
# the two themes sit far either side of this and the exact value is not
# delicate.
LIGHT_THEME_MIN_MEAN = 128

# Most screenshots are portal pages full of chrome, so OCR returning almost
# nothing means it failed to read the image rather than that the image is
# clean. A few captures are deliberately tiny crops of a single control, and
# those genuinely contain only a handful of words - failing on those forever
# would make the whole check something people learn to ignore.
MIN_EXPECTED_CHARS = 40
SMALL_CROP_PIXELS = 400_000

# OCR misreads characters constantly, so a hit is a prompt to look at the
# image rather than proof on its own. Normalising the easy confusions cuts the
# false negatives that would otherwise let a real identifier slip past.
CONFUSIONS = str.maketrans({"0": "o", "1": "l", "5": "s", "|": "l"})


def _load_config(*, allow_example: bool = False) -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    # The real config is gitignored, so a fresh clone does not have it. The
    # example only holds placeholders, so the literal sweep matches nothing and
    # only the email and GUID regexes survive - and a bare resource name is
    # neither. That is a materially weaker check, so it has to be asked for
    # explicitly rather than happening by default: this gate exists precisely
    # to avoid a green result nobody should trust.
    if not allow_example:
        raise SystemExit(
            f"Missing {CONFIG_PATH.name}.\n"
            f"  Copy {EXAMPLE_CONFIG_PATH.name} and fill in the identifiers from\n"
            "  your own deployment. It is gitignored because those values are\n"
            "  exactly what must not be published.\n"
            "  CI, which has no deployment, passes --allow-example-config to run\n"
            "  the email and GUID scans only."
        )
    if not EXAMPLE_CONFIG_PATH.exists():
        raise SystemExit(f"Missing {EXAMPLE_CONFIG_PATH.name}.")
    print(
        f"[warn] {CONFIG_PATH.name} not found; running with "
        f"{EXAMPLE_CONFIG_PATH.name}. Literal matching is reduced to "
        "placeholders - this run cannot detect a leaked resource name.",
        file=sys.stderr,
    )
    return json.loads(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))


def _load_ocr():
    """Return (engine_name, read_text) for whichever OCR engine is available.

    Tesseract reads portal chrome more accurately, but it is a system install
    that needs administrator rights. RapidOCR is pip-only, so the check stays
    runnable on a locked-down machine - which matters, because a privacy gate
    nobody can run is a privacy gate nobody runs.
    """

    try:
        import pytesseract
        from PIL import Image

        pytesseract.get_tesseract_version()
    except Exception:  # noqa: BLE001 - any failure means fall through to RapidOCR
        pass
    else:

        def read_tesseract(path: Path) -> str:
            return str(pytesseract.image_to_string(Image.open(path)))

        return "tesseract", read_tesseract

    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise SystemExit(
            "No OCR engine available. Install either:\n"
            "  pip install rapidocr-onnxruntime      (no admin rights needed)\n"
            "  pip install pillow pytesseract + winget install UB-Mannheim.TesseractOCR\n"
            "Refusing to report a pass without actually reading the images."
        ) from exc

    engine = RapidOCR()

    def read_rapidocr(path: Path) -> str:
        result, _elapsed = engine(str(path))
        return "\n".join(str(line[1]) for line in (result or []))

    return "rapidocr", read_rapidocr


def _findings(text: str, config: dict) -> list[str]:
    found: list[str] = []
    folded = text.casefold()
    folded_fuzzy = folded.translate(CONFUSIONS)

    for literal, _replacement in config["literals"]:
        needle = literal.casefold()
        if needle in folded or needle.translate(CONFUSIONS) in folded_fuzzy:
            found.append(literal)

    allowed_domains = {d.casefold() for d in config["allowedEmailDomains"]}
    for match in EMAIL.findall(text):
        if match.rsplit("@", 1)[-1].casefold() not in allowed_domains:
            found.append(match)

    allowed_guids = {g.casefold() for g in config["allowedGuids"]}
    for match in GUID.findall(text):
        if match.casefold() not in allowed_guids:
            found.append(match)

    return found


def main() -> int:
    config = _load_config(allow_example="--allow-example-config" in sys.argv)
    engine_name, read_text = _load_ocr()
    # Imported here, not at module scope: the matching logic is unit-tested
    # without any of the optional imaging dependencies installed.
    from PIL import Image

    print(f"OCR engine: {engine_name}\n")

    images = sorted(IMAGE_DIR.glob("*.png"))
    if not images:
        print(f"No images found in {IMAGE_DIR.relative_to(REPO_ROOT)}.", file=sys.stderr)
        return 1

    failures: list[tuple[Path, list[str]]] = []
    unreadable: list[Path] = []
    dark: list[Path] = []
    for path in images:
        text = read_text(path)
        with Image.open(path) as image:
            is_small_crop = (image.width * image.height) < SMALL_CROP_PIXELS
            # Both portals follow prefers-color-scheme, so a capture session
            # that spans a theme change yields a half-light, half-dark set.
            # Nothing else notices; this was found by eye after it shipped.
            grey = image.convert("L")
            grey.thumbnail((160, 160))
            pixels = list(grey.convert("L").tobytes())
            if sum(pixels) / len(pixels) < LIGHT_THEME_MIN_MEAN:
                dark.append(path)
        if len(text.strip()) < MIN_EXPECTED_CHARS and not is_small_crop:
            unreadable.append(path)
            print(f"  [{'?':4}] {path.name} - OCR returned almost no text")
            continue
        hits = _findings(text, config)
        status = "LEAK" if hits else "ok"
        print(f"  [{status:4}] {path.name}")
        if hits:
            failures.append((path, sorted(set(hits))))

    print(f"\nScanned {len(images)} image(s).")
    if dark:
        print(
            f"\n{len(dark)} image(s) look dark-themed. Screenshots in this repo are "
            "captured light; recapture with "
            'page.emulateMedia({ colorScheme: "light" }):',
            file=sys.stderr,
        )
        for path in dark:
            print(f"  {path.relative_to(REPO_ROOT)}", file=sys.stderr)
    if unreadable:
        print(
            f"\n{len(unreadable)} image(s) produced no readable text, so nothing was "
            "verified about them:",
            file=sys.stderr,
        )
        for path in unreadable:
            print(f"  {path.relative_to(REPO_ROOT)}", file=sys.stderr)
    if failures:
        print(
            f"\n{len(failures)} image(s) contain identifiers that must not be published:",
            file=sys.stderr,
        )
        for path, hits in failures:
            print(f"  {path.relative_to(REPO_ROOT)}: {', '.join(hits)}", file=sys.stderr)
        return 1

    if unreadable:
        return 1

    if dark:
        return 1

    print("No forbidden identifiers detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
