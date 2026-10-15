# OpenWebUI / Embedded corrective package

Base: v0.18, 24a9c4074d90c3cfcbfdf85dacd7f65562dc259e.

OpenWebUI Proxy and Chat share real HTTPX client options: `ssl_verify=True`,
`trust_env=False` by default. GUI checkboxes persist JSON booleans. CLI explicit
flags override saved values; `--use-config` loads them, otherwise defaults apply.
Per-field typed migration ignores unknown/invalid fields without losing valid
URL/token values. Tokens remain plain JSON. HTTPS scheme and disabled redirects
are unchanged. Direct and owned Embedded retain verify=True/trust_env=False.
No application code mutates process proxy environment.

Dedicated runtime callback / Qt signal updates Embedded status in the main thread
for doctor and batch preflight. It reports selected mode, backend, device, offload
proof or CPU and fallback causes. Startup/cancellation and inference failures clear
stale success. Strict GPU selection and pinned runtime/model assets are unchanged.

Focused tests cover typed migration, GUI restart, CLI precedence, real AsyncClient
arguments across both APIs/all option pairs in doctor and convert, prefixed URLs,
self-signed loopback HTTPS and proxy/NO_PROXY environment behavior, main-thread
status delivery in doctor/batch, fallback and runtime GPU OOM invalidation.
Self-signed fixture requires OpenSSL executable (explicit skip if unavailable).
All model/GPU fixtures are synthetic and do not qualify hardware or live OpenWebUI.

Evidence is kept outside Git under `.evidence/connection-fix/` and handoff archive:
actual GUI network log from synthetic HTTP loopback, actual dedicated CPU status
from owned synthetic engine, full local JUnit results, CI/run metadata.
No personal server URL, user token, OCR document or model is included.

LIVE_OPENWEBUI=PENDING. WINDOWS_GPU_HARDWARE=PENDING.
Windows build/frozen smoke and candidate publication require successful remote
workflow gates; infrastructure denial is not a product test PASS.
