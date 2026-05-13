# Overview

## Who manages OpsRadar

OpsRadar usually has four operating roles:

- `Platform admin`: manages workspaces, intake rules, AI settings, and role assignments
- `Approver`: reviews and decides requests in the Approval Inbox
- `IT or fulfillment operator`: completes approved work and closes the coordination loop
- `Auditor or reviewer`: checks the event trail and exported audit history

## What problem the managing team is solving

The problem is not missing tools. The problem is missing canonical state.

Without OpsRadar, the same request may exist in Slack, email, Jira, and someone’s memory at the same time. OpsRadar turns that into one request record with one visible owner, one status, and one audit trail.

## Operating rule

If an approval is not recorded in OpsRadar, it should not count as an official approval.

That rule prevents shadow approvals in direct messages and makes later audits defensible.

## Current practical workflow

1. A requester creates a request from the Request Catalog or a controlled intake source.
2. OpsRadar creates the request record and writes timeline events.
3. Role-based routing creates approval tasks.
4. Approvers decide or ask for more information.
5. Approved requests move into a simulated fulfillment task.
6. An admin marks fulfillment complete.
7. OpsRadar records completion and leaves a full event trail.

## Where operators work

- `Projects` for workspaces
- `Request Catalog` for structured request creation
- `Approval Inbox` for decisions
- `Intake Sources` for connector and intake-rule management
- `Role Builder` for routing inputs
- `Friction Dashboards` for basic request metrics

See the [Navigation Guide](navigation.md) for a plain-language explanation of every sidebar option.
