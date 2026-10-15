# Embedded GPU / HTTP diagnostics audit

Source base: v0.13 / 9939875118e9d02f438a80a3cbf8b7fc53fdc275.
Initial implementation reserved v0.14. A required final exception-redaction fix
uses v0.15. The post-ready native GPU error audit required v0.16; earlier tags
remain immutable.
Final exact commit, tag, CI/release results and artifact hashes belong to the local
handoff evidence produced after the push, not to a version bump commit.

Implemented: shared Auto/GPU/CPU selection, isolated pinned CPU/CUDA/Vulkan engines,
strict full LLM + CLIP evidence, bounded drained diagnostics, cancellable owned
processes, immutable worker settings, persisted device selection, common HTTP trace
callback through doctor and batch preflight, Qt signal delivery and rotating log.

Available hardware: Linux x86_64, NVIDIA RTX A4000 16 GB, driver 615.78.08.
Pinned Linux b11612 CUDA 13.4 reports ARCHS including 860, 18/18 LLM layers,
CLIP CUDA0 backend and GPU vision compute buffers. Same pinned F16 model/projector
passes synthetic 3×3 and 30×3 XLSX gold on CPU, GPU and Auto (Auto selects CUDA).
First measured run: process model load CPU 1.470s / GPU 0.860s;
OCR pipeline 3 rows CPU 4.323s / GPU 0.591s; 30 rows CPU 56.978s / GPU 5.692s.
These are same-host measurements, with OS file cache present; no disk-cold claim.
Per-inference measurements and repeated runs are in machine-readable handoff files.
They do not qualify Windows CUDA 12.4, Vulkan, every supported architecture, or
accuracy on user documents. No independent human gold is available for tabl3_1_a.jpg.

Windows GPU hardware: GPU_HARDWARE_PENDING. Clean Windows VM and real internet-
disconnected GPU tests: PENDING. Windows CPU frozen 3/30 row qualification and
assembly are required by the existing release gate. GPU-capable Portable must be
labelled an unqualified GPU candidate while these conditions remain.

OPENWEBUI_DIAGNOSTICS: automated transport/GUI evidence; real user server PENDING.
Mock examples use only loopback or reserved example domains:
`GET https://host.example:8443/prefix/ollama/api/tags`,
`GET https://host.example:8443/prefix/api/models`,
`POST https://ocr.example:9443/base/ollama/api/generate`,
`POST https://ocr.example:9443/base/api/chat/completions`.
Cases cover 200/401/403/404/405/422/502, 301/302/307/308 Location, TLS certificate
failure, DNS, refused connection, proxy exception, four httpx timeout stages,
retry attempts, actual model/payload, bounded fragments, no image/token leakage,
GUI doctor and service preflight events. Existing Ollama/Chat/Proxy semantics,
canonical tables, spans, XLSX fidelity and atomic cancellation tests remain.

Reproduce: commands in docs/TESTING.md. Handoff excludes weights, binaries and
user documents/images/OCR outputs; only synthetic machine reports/logs are included.

Final error strings and unexpected Qt worker exceptions also redact the configured
token; original exception chains remain available in memory and are redacted when
formatted into diagnostics. URL validation events explicitly carry URL_INVALID.

The post-ready OOM regression uses a fake engine that successfully loads then emits
a native CUDA OOM and exits. Strict GPU preserves GPU_OOM and never starts CPU;
ordinary completion text is discarded. This test is not hardware qualification.
Windows frozen qualification now records model startup, each OCR request latency
and full pipeline time separately from its actual --debug-http CLI trace.
