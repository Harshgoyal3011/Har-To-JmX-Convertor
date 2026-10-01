# Automatic deployment

The repository includes a Render Blueprint and a GitHub Actions CI workflow.
After the one-time hosting connection, every push to `main` runs the tests and
an installed-package web smoke check. Render deploys the commit when its checks
pass. Pull requests run the checks without deploying to the live service.

## Connect the service once

1. Sign in to [Render](https://dashboard.render.com/) and connect GitHub.
2. Choose **New > Blueprint**, select
   `Harshgoyal3011/Har-To-JmX-Convertor`, and use the `main` branch.
3. Apply the `render.yaml` Blueprint and wait for the initial deployment.

The Blueprint creates a free Python web service named `har-to-jmx-convertor`.
Render assigns its public HTTPS address. No deployment API key or GitHub
repository secret is required: Render's GitHub integration handles deployments.
The deployment files must first be pushed to GitHub for Render to find them.

If you already have a Render service, configure it to use this repository's
`main` branch, the commands and environment below, and **Auto-Deploy > After CI
Checks Pass**. Use this existing service instead of creating a second one.

## Runtime configuration

| Setting | Value |
| --- | --- |
| Runtime | Python 3.14.6 |
| Build command | `python -m pip install .` |
| Start command | `har2jmx` |
| Health check | `/healthz` |
| `HAR2JMX_HOST` | `0.0.0.0` |
| `PORT` | Assigned by Render; read automatically by the app |
| `HAR2JMX_OUTPUT` | `/tmp/har2jmx-generated` |

`HAR2JMX_PORT` overrides `PORT` when explicitly set. Local runs still default to
`127.0.0.1:8000`.

Generated downloads use temporary storage and disappear after restarts or
deployments. Download the conversion bundle before a deployment. The free
service can sleep while idle, so its first request can take longer. This setup
uses one service instance; it does not share generated files across replicas.

## Verify and troubleshoot

Open the Render service URL and upload a sample HAR. `/healthz` should return
HTTP 200 with `{"status": "ok"}`. Subsequent commits should appear in GitHub
Actions and then in Render's deployment history.

If a deployment does not start, check that CI passed, the service is linked to
`main`, and auto-deploy is set to wait for checks. If a deployment fails, inspect
the Render build/runtime logs; a failed health check should prevent the new
instance from becoming ready. For rollback, deploy a known-good commit from
Render or revert the change in GitHub so the normal pipeline deploys the revert.
