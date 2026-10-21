# Remote Keyboard development rules

- Source of truth: this repository. Public source code, no credentials, 6-digit pairing PINs, device names, Tailnet hostnames, addresses, screenshots of personal data, or personal documents in commits.
- Purpose: iPhone Safari's native text keyboard sends only confirmed text and a few explicitly allowed keys to a Windows receiver.
- Transport: keep the Windows HTTP receiver bound to 127.0.0.1:8787 and reach it with Tailscale Serve HTTPS. Never turn on Funnel, public port forwarding, CORS wildcard, or a hosted public key-injection endpoint.
- No hardcoded session tokens, access secrets, or unattended keyboard automation. The user must start input from the phone; support pause and timeout.
- Keep pairing validation, CSRF/origin restrictions, rate limiting and deduplication when making changes.
- Test Python protocol with `python -m unittest discover -s tests -v`. Real Windows SendInput and iPhone Safari IME behavior require separate physical-device checks.
- A successful commit is not proof of a working iPhone-to-PC connection. Record each milestone separately.
- Do not modify App Factory's repository-creation credentials or the user's existing Tailscale Serve mappings.
