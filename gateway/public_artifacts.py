"""Response policy for untrusted, revocable public workspace files.

This is an interim origin boundary until artifacts have a separate serving site. A response
sandbox applies to direct navigation as well as frames. Never add allow-same-origin: scripts
must not inherit the console/API origin or its browser storage. Basic classic-script previews
still work; storage, forms, popups and origin-dependent module/fetch apps deliberately do not.
Apply regardless of MIME so SVG, XHTML and future renderable formats cannot bypass the gate.
"""

PUBLIC_ARTIFACT_CSP = (
    "sandbox allow-scripts; base-uri 'none'; object-src 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)


def public_artifact_headers() -> dict[str, str]:
    return {
        "Content-Security-Policy": PUBLIC_ARTIFACT_CSP,
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }
