# Slack Intake

## What Slack is in OpsRadar

Slack is a structured intake channel, not a free-text mining source.

That means OpsRadar should accept Slack requests through a controlled mechanism such as a slash command, modal, or button flow. It should not parse arbitrary channel history and treat it as official request state.

## Current implementation

The backend currently exposes:

- `POST /api/v1/slack/commands`
- Slack intake source records through the OpsRadar intake-source APIs

The `Intake Sources` page now provides a direct `Add Slack Intake` path for operators.

## Who manages Slack intake

Slack intake is usually managed by:

- a platform admin in OpsRadar
- a Slack app admin who can configure slash commands and signing secrets

## Required setup

### 1. Create the intake rule in OpsRadar

Go to `Intake Sources` and create a Slack intake source with:

- workspace
- human-readable rule name
- allowed Slack channel or scope
- confidence threshold
- optional human confirmation requirement

### 2. Configure the backend signing secret

Set:

```bash
OPSRADAR_SLACK_SIGNING_SECRET=your_slack_signing_secret
```

This secret is used to validate `x-slack-signature` and `x-slack-request-timestamp`.

### 3. Point the Slack slash command at OpsRadar

Configure the Slack app to send commands to:

```text
https://<your-host>/api/v1/slack/commands
```

For local development, expose the local backend through a tunnel or reverse proxy. Slack cannot call `localhost` directly from the public internet.

## Example slash command usage

Current structured command shape:

```text
/opsradar request email=user@example.com resource=Figma access=editor workspace=<workspace_id>
```

If the workspace has a matching enabled Slack intake rule, OpsRadar will:

1. validate the Slack signature
2. create the request
3. start the normal submission lifecycle
4. route approvals based on workspace role assignments

## Operational limits

- Slack intake does not replace the request record inside OpsRadar
- Slack does not become the canonical approval timeline
- if Slack is not configured as an intake source, the request should be rejected
- if the request needs more detail later, operators should continue in OpsRadar, not in hidden DMs

## Day-two operating checklist

- confirm the Slack intake source is enabled
- verify the allowed channel or scope is still correct
- test one request after rotating the signing secret
- review the Approval Inbox to confirm requests are routing to the right people
- inspect the request timeline after each test
