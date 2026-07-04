# Fieldbase vs ONA — an honest comparison

## The correct framing

Neither ONA nor Fieldbase has a proprietary mobile app. **Both collect data with
ODK Collect (offline Android) and Enketo (web forms).** They are the same at the
field-collection layer.

- **ONA stack** = onadata (OpenRosa server) + ONA's web platform.
- **Fieldbase stack** = ODK Central / ONA / Kobo (OpenRosa server) + Fieldbase.

So **Fieldbase + ODK Central is architecturally the same shape as ONA.** The only
real difference is the *web platform layer* on top of the OpenRosa server — and
that is where each product makes different bets.

| | ODK collection client | OpenRosa server | Web platform |
|---|---|---|---|
| **ONA** | ODK Collect / Enketo | onadata | ONA platform (+ Akuko, OpenSRP) |
| **Fieldbase** | ODK Collect / Enketo | ODK Central / ONA / Kobo | Fieldbase |

## Layer-by-layer

| Dimension | **ONA** | **Fieldbase (+ ODK Central)** |
|---|---|---|
| Offline mobile collection | ODK Collect / Enketo | **Same** — ODK Collect / Enketo |
| OpenRosa server | onadata | ODK Central (or ONA / Kobo) |
| Form authoring | XLSForm + online builder | In-app builder → XLSForm, **+ AI protocol→form**, **+ Terminag vocabulary** |
| Review / QA workflow | Basic edit/delete | **2-gate endorse→validate→decline**, append-only review log, raw-vs-edited audit |
| Roles / RBAC | Org accounts, per-form sharing | Hierarchical roles scoped region→country→project |
| Multi-tenancy | Org accounts (shared hosting) | Institution isolation (row-level + optional per-tenant DB / self-host) |
| M&E / analytics | Maps, charts, XLS Reports; **Akuko** (separate) | KPI dashboards, threshold alerts, completion grids, validation-flag engine |
| Standardization | Free-form XLSForm fields | Terminag controlled vocabulary + config-driven field mappings |
| Add a use-case | New form, manual | Config/YAML-driven |
| Identity | Per-account | Central registry, stable UserID on submissions, server-account auto-provisioning |
| Maturity / hosting | **Production, hosted, multilingual support** | In active build, self-hosted |

## Where ONA is ahead (today)
- **Maturity & hosting** — production-proven, supported, no ops burden.
- **Polished analytics** — Akuko is a strong dashboarding product.
- **Adjacent products** — OpenSRP for health service delivery.

## Where Fieldbase adds what ONA's web layer doesn't
- **Structured review/QA with an audit trail** (ONA only lets you edit records).
- **Institution-scoped RBAC + multi-tenancy** (ONA sharing is per-form).
- **M&E as a first-class layer** — KPIs, alerts, completion grids built in.
- **Cross-project standardization** — Terminag vocabulary + config mappings.
- **Config-driven use-case onboarding** — the core reason for the rebuild.

## Bottom line
> **ONA and Fieldbase are the same stack shape.** Both ride ODK Collect + Enketo
> on an OpenRosa server. Once ODK Central is deployed under Fieldbase, we have a
> functional equivalent of ONA — with a stronger governance / review / M&E layer,
> and (for now) less maturity and no hosted option. We compete at the web layer,
> not at collection.
