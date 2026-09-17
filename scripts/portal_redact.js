/*
 * Sanitises the Microsoft Foundry portal DOM before a workshop screenshot,
 * and works out where page content actually ends so captures can be cropped
 * instead of shipping half a screen of empty background.
 *
 * The repo is public and the screenshots come from a real deployment, so
 * identifiers are rewritten in the DOM *before* the pixels are produced.
 * Blurring afterwards leaves the original bytes on disk; this way the
 * sensitive value never reaches the PNG at all.
 *
 * Two classes of rule, and the second exists because the first is not enough.
 * Literal replacement only finds strings you already knew about - it silently
 * passed a portal grid whose "Created by" column held a tenant admin UPN that
 * nobody had listed. Anything shaped like an email address or a GUID is
 * therefore replaced wholesale, and the return value asserts none survived.
 *
 * Two traps that both shipped a leaking screenshot before being fixed:
 *
 * 1. `document.body.innerText` does NOT include `<input>` values. A combobox
 *    holding a real resource name passed the residual check and appeared,
 *    unredacted, in the PNG. Input values are scrubbed and asserted here.
 *
 * 2. The Azure portal renders blade content in IFRAMES. Running this in the
 *    top frame only redacts the page title while leaving the subscription ID,
 *    resource group and hostnames untouched in the blade. It MUST be applied
 *    to every frame, and every frame's residual report must be empty:
 *
 *      for (const frame of page.frames()) {
 *        await frame.evaluate(portalRedact);
 *        const report = await frame.evaluate(() => window.__redact());
 *      }
 *
 * Beware: scrubbing MUTATES input values. Never submit a form while the page
 * is redacted or you will send the fake value. Reload, re-enter the real
 * values, submit, and only then redact for the capture.
 *
 * Usage, from the browser tooling driving the capture. The identifiers live in
 * `portal_redact.config.json`, which is gitignored precisely because it holds
 * the real tenant values - see `portal_redact.config.example.json`. Pass it in
 * rather than hardcoding, or this file publishes the strings it exists to
 * scrub.
 *
 * `addInitScript` only *installs* these helpers on each navigation - it does
 * not scrub anything by itself, and a page that re-renders after a scrub will
 * show the original values again. Call `__redact()` immediately before every
 * screenshot, after the page has settled, and check the report each time:
 *
 *   const config = JSON.parse(fs.readFileSync("scripts/portal_redact.config.json"));
 *   await page.addInitScript(portalRedact, config);
 *   const report = await page.evaluate(() => window.__redact());
 *   // report.residual* must all be empty, or the capture is discarded
 *   const clip = await page.evaluate(() => window.__clip());
 *   await page.screenshot({ path, clip });
 *
 * A single pass is not enough on virtualised grids. The Azure portal resource
 * list renders rows lazily, so a scrub can run, report zero residuals because
 * the rows do not exist yet, and then the rows arrive unredacted. Loop until a
 * pass reports `changed === 0` across every frame, wait, and confirm it is
 * still 0 before capturing.
 *
 * Two more capture notes, both learned by shipping the wrong picture:
 *
 * - Both portals follow `prefers-color-scheme`, so the same page captures
 *   light or dark depending on the machine, and a session that spans a theme
 *   change silently produces a half-and-half image set. **Light is the
 *   standard for this repo.** Pin it before every capture:
 *   `await page.emulateMedia({ colorScheme: "light" })`.
 * - The Azure portal renders its blade in an iframe and will not paint at all
 *   if this runs at document-start. Use `addScriptTag` after load rather than
 *   `addInitScript`; the Foundry portal tolerates either.
 */
function portalRedact(config) {
  const LITERALS = config.literals;
  const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
  const GUID = /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/g;
  const SAFE_EMAIL = config.safeEmail;
  const SAFE_GUID = config.safeGuid;

  const scrub = (value) => {
    let out = value;
    for (const [needle, replacement] of LITERALS) {
      if (out.includes(needle)) {
        out = out.split(needle).join(replacement);
      }
    }
    return out.replace(EMAIL, SAFE_EMAIL).replace(GUID, SAFE_GUID);
  };

  window.__redact = () => {
    let changed = 0;

    if (!document.body) {
      return { changed: 0, blurred: 0, residualLiterals: [], residualEmails: [], residualGuids: [] };
    }

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) {
      nodes.push(walker.currentNode);
    }
    for (const node of nodes) {
      const value = scrub(node.nodeValue);
      if (value !== node.nodeValue) {
        node.nodeValue = value;
        changed += 1;
      }
    }

    // innerText never reports these, so a leak here passes every text check.
    for (const el of document.querySelectorAll("input,textarea")) {
      if (el.value) {
        const value = scrub(el.value);
        if (value !== el.value) {
          el.value = value;
          changed += 1;
        }
      }
    }

    // Tooltips and aria labels render as visible text on hover in some grids.
    // href is included because the portal puts resource IDs in link targets.
    for (const el of document.querySelectorAll("[title],[aria-label],[alt],[href]")) {
      for (const attr of ["title", "aria-label", "alt", "href"]) {
        const current = el.getAttribute(attr);
        if (!current) {
          continue;
        }
        const value = scrub(current);
        if (value !== current) {
          el.setAttribute(attr, value);
          changed += 1;
        }
      }
    }

    let blurred = 0;
    for (const el of document.querySelectorAll('button[aria-label="My profile settings"]')) {
      el.style.filter = "blur(6px)";
      blurred += 1;
    }

    let text = document.body.innerText;
    for (const el of document.querySelectorAll("input,textarea")) {
      text += "\n" + (el.value || "");
    }
    return {
      changed,
      blurred,
      residualLiterals: LITERALS.map(([n]) => n).filter((n) => text.includes(n)),
      residualEmails: (text.match(EMAIL) || []).filter((e) => e !== SAFE_EMAIL),
      residualGuids: (text.match(GUID) || []).filter((g) => g !== SAFE_GUID),
    };
  };

  // Scoped to <main>: the left rail pins a collapse control to the bottom of
  // the viewport, so a document-wide scan always reports a full-height page.
  window.__clip = () => {
    const viewportHeight = window.innerHeight;
    const root = document.querySelector("main") || document.body;
    let bottom = 0;
    for (const el of root.querySelectorAll("*")) {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      if (style.visibility === "hidden" || style.display === "none") {
        continue;
      }
      if (rect.height === 0 || rect.width === 0 || rect.height > viewportHeight * 0.8) {
        continue;
      }
      if (rect.bottom > bottom && rect.bottom <= viewportHeight) {
        bottom = rect.bottom;
      }
    }
    return {
      x: 0,
      y: 0,
      width: document.documentElement.clientWidth,
      height: Math.min(viewportHeight, Math.ceil(bottom + 32)),
    };
  };
}
