# Deployment Runbook

End-to-end guide for deploying Narrative to OpenShift using GitHub Actions, Artifactory, and Vault via the External Secrets Operator.

---

## Prerequisites checklist

- [ ] OpenShift namespace exists (`oc new-project your-namespace`)
- [ ] ESO is installed in the cluster and a `ClusterSecretStore` named `vault-backend` exists
- [ ] Artifactory Docker registry is accessible from the cluster (imagePullSecret or registry whitelist)
- [ ] GitHub repo has the required secrets and variables configured (see below)
- [ ] You have `oc` CLI access with admin rights to the namespace

---

## Step 1 — Add secrets to Vault

Run once as a Vault admin. These become the org-wide defaults that all channels fall back to.

```bash
vault kv put secret/narrative/slack \
  bot_token="xoxb-..." \
  signing_secret="..." \
  app_token="xapp-..."        # only needed if you ever switch to Socket Mode

vault kv put secret/narrative/jira \
  base_url="https://yourcompany.atlassian.net" \
  email="slack-bot@yourcompany.com" \
  api_token="..." \
  target_status="Ready for Sprint" \
  labels_to_remove="needs-pointing,unpointed" \
  story_points_field="customfield_10016"
```

To update a value later (e.g. rotate the Jira API token):
```bash
vault kv patch secret/narrative/jira api_token="new-token"
```
ESO will pick up the change within the `refreshInterval` (default 1h). Force an immediate sync:
```bash
oc annotate externalsecret narrative-secret \
  force-sync=$(date +%s) --overwrite -n your-namespace
```

---

## Step 2 — Configure GitHub Actions

### Repository Variables (Settings → Secrets and variables → Actions → Variables)

| Variable | Example value |
|---|---|
| `ARTIFACTORY_REGISTRY` | `your-org.jfrog.io` |
| `ARTIFACTORY_REPO` | `docker-local/narrative` |
| `OPENSHIFT_SERVER` | `https://api.cluster.example.com:6443` |
| `OPENSHIFT_NAMESPACE` | `your-namespace` |

### Repository Secrets (Settings → Secrets and variables → Actions → Secrets)

| Secret | How to get it |
|---|---|
| `ARTIFACTORY_USER` | Artifactory service account username |
| `ARTIFACTORY_PASSWORD` | Artifactory service account API key or password |
| `OPENSHIFT_TOKEN` | See below |

**Creating the OpenShift deploy token:**
```bash
# Create a service account for CI
oc create serviceaccount github-actions -n your-namespace

# Grant it edit rights (enough to apply manifests and update deployments)
oc adm policy add-role-to-user edit \
  system:serviceaccount:your-namespace:github-actions -n your-namespace

# Get the token (OpenShift 4.11+ uses token requests)
oc create token github-actions -n your-namespace --duration=8760h
```
Copy the output and save it as the `OPENSHIFT_TOKEN` secret in GitHub.

---

## Step 3 — Configure the Artifactory image pull secret

OpenShift needs credentials to pull the image from Artifactory at runtime.

```bash
oc create secret docker-registry artifactory-pull \
  --docker-server=your-org.jfrog.io \
  --docker-username=<svc-account> \
  --docker-password=<api-key> \
  -n your-namespace

# Link it to the default service account so all pods can pull
oc secrets link default artifactory-pull --for=pull -n your-namespace
```

---

## Step 4 — Update deploy manifests for your cluster

Edit these values before the first deploy:

**`deploy/pvc.yaml`**
- `storageClassName` — run `oc get storageclass` to see what's available

**`deploy/external-secret.yaml`**
- `secretStoreRef.name` — name of your ClusterSecretStore
- `secretStoreRef.kind` — `ClusterSecretStore` or `SecretStore`
- `namespace` — your OC_NAMESPACE

**`deploy/deployment.yaml`**
- `image` — your Artifactory registry path (the pipeline overwrites this on deploy, but set a valid value for the initial apply)
- `namespace` — your OC_NAMESPACE

**`deploy/route.yaml`**
- `namespace` — your OC_NAMESPACE
- Optionally set `spec.host` for a custom hostname

---

## Step 5 — First deploy

Push to `main` and the GitHub Actions pipeline runs automatically:

1. **test** — `npm test`
2. **build** — builds the Docker image, tags with `<short-sha>` and `latest`, pushes to Artifactory
3. **deploy** — applies all manifests, updates the image tag, waits for rollout

Monitor the deploy:
```bash
oc rollout status deployment/narrative -n your-namespace -w
oc logs -f deployment/narrative -n your-namespace
```

Get the public URL:
```bash
oc get route narrative -n your-namespace -o jsonpath='{.spec.host}'
```

---

## Step 6 — Wire up Slack

Take the Route hostname and update your Slack App at [api.slack.com/apps](https://api.slack.com/apps):

| Setting | Value |
|---|---|
| Event Subscriptions → Request URL | `https://<route-host>/slack/events` |
| Interactivity → Request URL | `https://<route-host>/slack/events` |
| Slash Commands → `/point` Request URL | `https://<route-host>/slack/events` |
| Slash Commands → `/point-config` Request URL | `https://<route-host>/slack/events` |

Slack will send a challenge request to verify the URL — the bot handles this automatically.

---

## Ongoing operations

### Roll back to a previous image
```bash
oc rollout undo deployment/narrative -n your-namespace
```

### Scale down (maintenance window)
```bash
oc scale deployment/narrative --replicas=0 -n your-namespace
```

### View current config-store (channel configs)
```bash
oc exec deployment/narrative -n your-namespace -- cat /app/data/config-store.json
```

### Rotate secrets
Update the value in Vault, then force ESO to re-sync (see Step 1).  
The pod does **not** need to restart — envFrom secrets are reloaded on the next pod start, so do a rolling restart to pick up immediately:
```bash
oc rollout restart deployment/narrative -n your-namespace
```

### Check ESO sync status
```bash
oc get externalsecret narrative-secret -n your-namespace
# READY=True means the K8s Secret is in sync with Vault
```
