# Remote Keyboard roadmap

## v0.1 prototype
- [x] Windows localhost-only receiver (Python stdlib, SendInput)
- [x] Responsive iPhone Safari page with native Japanese keyboard
- [x] Pairing PIN, cookie session, pause, idle timeout, origin check
- [x] Event-ID deduplication and recovery warning for ambiguous delivery
- [x] Five Python protocol tests in a Linux non-Windows environment
- [ ] Actual iPhone Safari → Tailscale Serve → Windows Notepad test
- [ ] Verify Japanese conversion, punctuation, emoji, delete, repeated edits, orientation and background/resume
- [ ] Review using a PC with multiple windows and changing focus
- [ ] Review startup and shutdown with any existing Tailscale Serve configuration

## Next
- [ ] Improve IME event handling based on real device logs without logging typed content
- [ ] A user-friendly way to discover the private Tailnet URL locally
- [ ] Optional PIN reset/rotation and clearer connection state
- [ ] Harden session recovery and text editing cursor movement
- [ ] Signed binary build only after a verified Windows test

## Safety boundaries
No public relay server or GitHub Pages hosted control endpoint is required. Source code may be public, but Windows receiver and pairing are not public.
