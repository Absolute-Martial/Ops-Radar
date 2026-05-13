# OpsRadar Operator Documentation

OpsRadar is the system of record for internal requests that are otherwise scattered across Slack, Jira, email, and direct messages.

This documentation is for the people who run OpsRadar day to day:

- platform admins who configure workspaces, roles, and intake
- approvers who need a clear approval queue
- IT or operations staff who fulfill approved work
- auditors or reviewers who need a trustworthy request timeline

Use this docs site to operate the current implementation, not an idealized future state.

## What OpsRadar does today

- accepts structured requests from the Request Catalog
- supports controlled intake rules, including Slack as a structured intake source
- routes requests into approval records based on role assignments
- records policy evaluation, approval actions, fulfillment tasks, and audit events
- tracks request lifecycle metrics in Friction Dashboards

## What to read first

- [Overview](operators/overview.md) if you manage the product
- [Navigation Guide](operators/navigation.md) if you want to understand the sidebar options
- [Request Lifecycle](operators/request-lifecycle.md) if you run approvals or fulfillment
- [Roles And Ownership](operators/roles-and-ownership.md) if you manage routing
- [Slack Intake](operators/slack-intake.md) if you want structured Slack request creation

## Local docs preview

Material for MkDocs expects a `mkdocs.yml` file at the project root and Markdown content in `docs/`.

```bash
pip install -r docs/requirements.txt
mkdocs serve
```

If you prefer Docker, the official Material image also works:

```bash
docker run --rm -it -p 8000:8000 -v ${PWD}:/docs squidfunk/mkdocs-material
```
