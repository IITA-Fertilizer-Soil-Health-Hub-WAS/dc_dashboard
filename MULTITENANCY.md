# Multi-tenancy & data isolation

Several institutions can use this platform without ever seeing each other's data.
Every region, use case, and user belongs to exactly one **Organization** (tenant),
and the scoping facade (`apps/rbac/permissions.py`) filters by it, so isolation
holds at the query layer — not just in the UI.

The same codebase runs in two modes.

## 1. Multi-tenant (central / hosted)

The hub hosts one deployment; each institution is an `Organization` in the shared
database. Isolation is enforced in-app:

- `visible_use_cases()` returns only the signed-in user's institution's projects
  (a hub operator — a Django superuser with no organization — spans all tenants).
- **Team & access**: the existing-user list, grants, and approvals are bounded to
  the actor's institution; a cross-institution grant is rejected.
- A user belongs to exactly one institution, set when they are first approved.

Add an institution and onboard its projects:

```bash
python manage.py create_organization "Institution Name" --code inst
# then onboard projects via the wizard and pick the owning institution,
# or in YAML:  use_case: { code: ..., organization: inst, ... }
```

## 2. Single-tenant (self-hosted)

An institution that wants **physical** separation runs its own deployment with
its own database. The same code, with exactly one `Organization` — everything
joins it implicitly (`apps/usecases/tenancy.py: default_organization()`), so no
per-request tenant resolution is needed.

```bash
python manage.py migrate
python manage.py create_organization "Their Institution" --code theirs
# create the first admin in-app via /claim-admin/ (see README), then onboard.
```

## Collaboration (opt-in, owner-controlled)

Institutions can collaborate **without** weakening isolation. An owner invites a
specific external user to a **single project** (never a region or country) from
**Team & access → Invite a collaborator**. The collaborator keeps their home
institution and gains access only to that one project, which the owner can revoke
at any time. The owner's institution administers the share; the collaborator's
does not.

## Promoting an institution to its own deployment

When a hosted institution graduates to its own (single-tenant) deployment, export
everything it owns and load it into the fresh instance. All primary keys are
UUIDs, so the import never collides:

```bash
# on the shared instance
python manage.py export_organization inst --indent 2 > inst.json

# on the institution's new, empty single-tenant instance
python manage.py migrate
python manage.py loaddata inst.json
```

Decommissioning the institution's data on the shared instance afterwards is a
separate, deliberate step (delete the `Organization`; cascades remove its data).
`Organization.database_alias` is reserved for a future in-process
database-per-tenant router, should one ever be preferred over separate
deployments.
