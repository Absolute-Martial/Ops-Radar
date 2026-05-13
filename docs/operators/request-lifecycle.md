# Request Lifecycle

## Current statuses in the implementation

The runtime now uses these request states:

- `draft`
- `submitted`
- `duplicate_review`
- `policy_check_pending`
- `pending_approval`
- `waiting_on_requester`
- `approved`
- `rejected`
- `escalated`
- `fulfillment_pending`
- `fulfilled`
- `completed`
- `failed`
- `cancelled`

## What each operator does

### Requester

- creates the request
- provides business reason and resource details
- responds if the request moves to `waiting_on_requester`

### Approver

- reviews requests assigned through role routing
- approves or rejects
- can request more information instead of leaving the request buried

### Fulfillment operator or admin

- monitors requests in `fulfillment_pending`
- manually marks the simulated fulfillment task complete
- closes the operational loop so the request reaches `completed`

## Timeline as source of truth

Every meaningful transition should be read from the request event stream, not inferred from UI appearance.

Typical timeline:

```text
Request created
Request submitted
Temporal workflow tracking started
Policy evaluated
Approval created
Approval approved or rejected
Request more info or fulfillment task created
Fulfillment started
Fulfillment completed
Request completed
```

## More-info loop

When an approver or fulfillment operator lacks information, the request should move to `waiting_on_requester` instead of silently stalling.

That does three things:

- makes the blocker visible
- records the reason in the timeline
- prevents the approver from appearing inactive when the requester is actually the blocker
