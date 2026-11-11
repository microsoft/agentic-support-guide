# Conformance goldens

The Python and .NET tracks are the same application written twice. This
folder is how that claim is tested rather than asserted.

`goldens/` is recorded by running the **Python** app. The .NET test suite
replays the same inputs against the .NET app and compares what comes back.
Anything that differs fails the .NET build, unless it is listed in
[allowed_differences.yaml](allowed_differences.yaml) with the reason the two
tracks may disagree there.

## What is recorded

| Path | What it pins down |
|------|-------------------|
| `scenarios/*.json` | HTTP behaviour end to end: configuration, the canned model replies, every request, every response, and every model call the request caused. |
| `data/*.json` | The synthetic data the app generates. Large sets are stored as a count, a SHA-256 of `json.dumps(rows)` and the first rows. |
| `instructions/*.txt` | The exact instructions each agent role sends, composed from `agents/<role>/agent.md`. |
| `schemas/*.json` | The structured-output schema each role asks the model for. |
| `determinations.json` | The domain rule: for every test sentence, whether it asserts a determination or denies human review. |
| `hosted.json` | The hosted agent's input bounding, untrusted-data fencing, JSON unwrapping and output gate. |

## Scenario format

```jsonc
{
  "scenario": "recommendation_ok",
  "config": {                     // how the app is started
    "provider": "fake",           // "fake" = canned model replies; absent = no provider configured
    "api_key": "…",               // API_SHARED_KEY; absent = no key configured
    "app_service": true,          // WEBSITE_SITE_NAME is set (App Service behaviour)
    "demo_reset_enabled": true    // DEMO_RESET_ENABLED=true
  },
  "replies": {                    // per agent role, consumed in order
    "data-analyst-agent": [
      { "json": { … } },          // the model returns this JSON
      { "text": "…" },            // the model returns this raw text
      { "error": "ThrottledError" } // the model call fails with this typed error
    ]
  },
  "steps": [
    {
      "request": {
        "method": "POST",
        "path": "/api/…?tail=5",  // tail=N: keep only the last N rows of a list response
        "json": { … },            // JSON body; absent = no body
        "body": "{",              // raw body instead of json, sent with content_type
        "content_type": "…",
        "auth": "key",            // "key" (default), "none" or "wrong"
        "headers": { … }
      },
      "response": {
        "status": 200,
        "headers": { … },         // only the headers listed in conformance_cases.py;
                                  // a redirect's location is recorded as path and query
        "json": { … }             // or "body": "" when empty, or "body_kind" for non-JSON
      },
      "model_calls": [ … ]        // role, deployment, instructions hash, settings, user message
    }
  ]
}
```

Every scenario starts a fresh app with no app environment variables set
except `BUILD_ID=conformance` and the three model deployment names, then
applies its `config`.

Values that cannot repeat between runs are replaced with placeholders
(`<uuid>`, `<now>`, `<ms>`); the .NET comparison accepts any value of the
right shape in their place.

## Regenerating

Change the Python app first, then re-record:

```powershell
python python/scripts/generate_conformance.py --write   # rewrite goldens/
python python/scripts/generate_conformance.py           # check only; exit 1 if stale
```

`python/services/api/tests/test_conformance.py` fails when a committed golden
no longer matches the Python code, so a Python change that is not re-recorded
cannot merge. The .NET tests then fail until the .NET app does the same thing.

The scenario definitions live in
[`python/services/api/tests/conformance_cases.py`](../python/services/api/tests/conformance_cases.py).
