# Roles And Ownership

## Why roles matter

Role Builder is not just descriptive UI. It feeds runtime routing.

OpsRadar uses role blueprints plus workspace role assignments to decide who should receive approval work for a request.

## Current operating model

Two layers are in play:

- `Role blueprints`: define role names, permissions, and approval authority
- `Workspace role assignments`: attach users to those roles for a specific workspace

## Practical routing behavior

For access-style requests, OpsRadar currently resolves approvers from workspace role assignments and prefers specific roles such as:

- `manager`
- `it_admin`
- `security_reviewer`

`super_admin` is treated as a fallback, not a mandatory extra approver when specific ownership exists.

## What the managing admin should do

1. Create or refine role blueprints in `Role Builder`
2. Assign real users to those roles in the workspace
3. Submit a test request from the Request Catalog
4. Confirm the Approval Inbox receives the request under the expected people
5. Inspect the request timeline and audit entries to verify the route

## Failure modes to watch

- no user assigned to a required role
- requester accidentally assigned as their own approver
- overuse of fallback admin approval instead of specific ownership
- high-risk requests missing security review
