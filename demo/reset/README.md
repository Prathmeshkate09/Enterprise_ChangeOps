# Demo reset

Every enterprise service exposes a tenant-scoped `/v1/reset` operation. The
Phase 2 scenario resets all four services before testing, making repeated local
runs deterministic without sharing tenant state.
