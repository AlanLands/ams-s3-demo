# Deploying the AMS S3 demo — step by step

Target environment: **one EC2 instance** in the TCS GenAI AWS account, LLM access
via **Amazon Bedrock**, purpose is a **live client demo**.

Follow the steps in order. Each one has a **Verify** command — don't move on
until it passes. Total time on a clean account: about 45 minutes, plus one full
rehearsal.

Conceptual background ("why one instance", architecture) is in the
[Appendix](#appendix-a--why-it-is-built-this-way) at the end. You don't need it
to deploy.

---

## Before you start

- [ ] Working AWS access to the target account — **see Part 0**, this is the part
      that usually blocks people
- [ ] The repo cloned locally, on the commit you intend to demo
- [ ] Node.js locally (to build the frontend — it does **not** need to be on the
      instance)
- [ ] An SSH key pair for the instance

Set these once in your local shell; the commands below reuse them:

```bash
export AWS_REGION=us-east-1          # the region with Bedrock model access
export INSTANCE=ubuntu@<public-ip>   # fill in after Step 3
```

---

# Part 0 — Get AWS access

In a TCS-managed account you will usually **not** have all three permissions
this guide needs. Two of them normally require the cloud/platform team. Sort
this out first — lead time here is measured in days, not minutes.

| Capability | Who normally does it |
|---|---|
| Launch EC2, attach an instance profile | **You**, if you have a developer permission set |
| Create an IAM role (Step 2) | **Platform team** — role creation is usually blocked by an SCP or permission boundary |
| Enable Bedrock model access (Step 1) | **Platform team** — account-level, often centrally governed |

## Step 0.1. Work out how the account authenticates you

Most enterprise AWS estates use **IAM Identity Center (SSO)** with short-lived
credentials, not static access keys. Ask which applies, then configure it:

```bash
aws configure sso
#   SSO session name : tcs
#   SSO start URL    : https://<your-org>.awsapps.com/start
#   SSO region       : <region>
#   ...then pick the account and permission set you were granted
aws sso login --profile <profile-name>
export AWS_PROFILE=<profile-name>
```

If instead you are issued static keys, `aws configure` is enough — but note
those expire or get rotated, which is a common silent failure (see 0.2).

## Step 0.2. Verify you are actually authenticated

Do this before anything else. Expired credentials fail in confusing ways
further down — a dead key surfaces as a **401 from Bedrock in Step 9**, which
looks like a Bedrock problem but is not.

```bash
aws sts get-caller-identity
```

| Result | Meaning |
|---|---|
| JSON with `Account` / `Arn` | Good — note the account id, confirm it is the intended one |
| `InvalidClientTokenId` | Credentials are invalid, expired, or revoked — re-run `aws sso login`, or get new keys |
| `ExpiredToken` | SSO session lapsed — `aws sso login` again |
| `Unable to locate credentials` | No profile configured — go back to 0.1 |

## Step 0.3. Find out what you can actually do

Read-only probes; none of these change anything.

```bash
# Can you see EC2, and could you launch? (--dry-run never creates an instance)
aws ec2 run-instances --dry-run --image-id ami-000000000000 \
  --instance-type t3.large --region "$AWS_REGION" 2>&1 | tail -1

# Can you create IAM roles?
aws iam list-roles --max-items 1 >/dev/null 2>&1 && echo "IAM: readable" || echo "IAM: denied"

# Is Bedrock visible, and is any Claude model already granted?
aws bedrock list-foundation-models --region "$AWS_REGION" \
  --query "modelSummaries[?contains(modelId,'claude')].modelId" --output table
```

Reading the EC2 dry-run result:

- `DryRunOperation` → you have `RunInstances`. (The fake AMI id is fine; the
  permission check happens first.)
- `UnauthorizedOperation` → you are authenticated, but lack the permission.
- `AuthFailure` → **not a permissions problem** — your credentials are dead.
  Go back to Step 0.2; nothing else in this guide will work until that is fixed.

If Bedrock returns an empty table or `AccessDeniedException`, model access is
not enabled — that is Step 0.4, and it is the long pole.

## Step 0.4. Request what is missing

Send the platform/cloud team a request naming exactly what you need. A vague
ask ("I need Bedrock") tends to bounce. Template:

> **Request: AWS access for an internal AI demo environment**
>
> Account: `<account id>` · Region: `<region>` · Needed by: `<date>`
>
> 1. **Bedrock model access** for an Anthropic Claude model in this region
>    (Bedrock console → Model access). Please confirm the exact granted model
>    id — it carries an `anthropic.` prefix.
> 2. **An IAM role + instance profile** named `ams-s3-demo-ec2`, trusted by
>    `ec2.amazonaws.com`, with only `bedrock:InvokeModel` and
>    `bedrock:InvokeModelWithResponseStream` on
>    `arn:aws:bedrock:*::foundation-model/anthropic.claude-*` and
>    `arn:aws:bedrock:*:*:inference-profile/*anthropic.claude-*`.
>    (Exact policy JSON attached: `deploy/aws/bedrock-iam-policy.json`.)
>    If I cannot create roles myself, please create it and grant me
>    `iam:PassRole` on it so I can attach it to the instance.
> 3. **Permission to launch one EC2 instance** (`t3.large`, Ubuntu 24.04) and
>    attach that instance profile.
> 4. **Network egress from the instance's subnet to the Bedrock endpoint**
>    (`bedrock-mantle.<region>.api.aws`), via NAT or a Bedrock VPC endpoint.
>
> No customer data is involved — all demo data is synthetic.

## Step 0.5. Adjust the guide to what you were granted

- **Role was pre-created for you** → skip Step 2 entirely; just attach the
  instance profile in Step 3.
- **You only got console access, no CLI** → every CLI command here has a console
  equivalent; the verification commands still work over SSH from the instance.
- **Bedrock refused outright** → the app still supports `anthropic`, `openai`,
  and `ollama` providers (`LLM_PROVIDER` in `.env`). `ollama` needs no outbound
  network at all and is the fallback for a fully sealed environment, at some
  cost to output quality.

**Do not continue past here until `aws sts get-caller-identity` succeeds and
Step 0.3 shows a Claude model.**

---

# Part A — AWS setup

## Step 1. Enable Bedrock model access

IAM permission alone is **not** enough. Claude models need an account-level
access grant in the Bedrock console, per region. This is the single most common
cause of a correct-looking setup still failing with `AccessDeniedException`.

1. Bedrock console → **Model access** → **Manage model access**
2. Enable the Anthropic Claude model you plan to use
3. Wait for status to read **Access granted**

**Verify:**

```bash
aws bedrock list-foundation-models --region "$AWS_REGION" \
  --query "modelSummaries[?contains(modelId,'claude')].modelId" --output table
```

The model you intend to use must appear. Note its exact id — you need it in
Step 6. Bedrock ids carry an `anthropic.` prefix.

## Step 2. Create the instance IAM role

The app authenticates to Bedrock through the **instance role**, not an API key.
Nothing secret ends up in `.env` (project hard rule 3).

```bash
# from the repo root, locally
aws iam create-role --role-name ams-s3-demo-ec2 \
  --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{"Effect":"Allow",
      "Principal":{"Service":"ec2.amazonaws.com"},
      "Action":"sts:AssumeRole"}]}'

aws iam put-role-policy --role-name ams-s3-demo-ec2 \
  --policy-name bedrock-invoke \
  --policy-document file://deploy/aws/bedrock-iam-policy.json

aws iam create-instance-profile --instance-profile-name ams-s3-demo-ec2
aws iam add-role-to-instance-profile \
  --instance-profile-name ams-s3-demo-ec2 --role-name ams-s3-demo-ec2
```

**Verify:**

```bash
aws iam get-role-policy --role-name ams-s3-demo-ec2 --policy-name bedrock-invoke
```

## Step 3. Launch the EC2 instance

| Setting | Value | Why |
|---|---|---|
| AMI | **Ubuntu 24.04 LTS** | Ships Python 3.12, matching the dev venv. Amazon Linux 2023 ships 3.11 and would need a separate Python build. |
| Type | **t3.large** (2 vCPU / 8 GB) | ChromaDB plus a `pytest` subprocess during codegen makes t3.micro/small unreliable. |
| Disk | 20 GB gp3 | |
| IAM instance profile | `ams-s3-demo-ec2` | From Step 2. |
| Security group | inbound **80** from the presenter's IP only; **22** for admin | Ports 8000/8501 bind to localhost — they must not be public. |

Then set `export INSTANCE=ubuntu@<public-ip>`.

**Verify — confirm the instance can actually reach Bedrock:**

```bash
ssh $INSTANCE 'curl -s -o /dev/null -w "%{http_code}\n" \
  https://bedrock-mantle.'"$AWS_REGION"'.api.aws/anthropic/'
```

Any HTTP response (including 403) proves the network route exists. A hang or
connection failure means the subnet has no egress path to Bedrock — fix that
before continuing, or add a Bedrock VPC endpoint.

---

# Part B — Get the code onto the box

## Step 4. Build the frontend locally

`apps/console/web/dist/` is gitignored, so it is **not** in the checkout. Build it here
and ship the output — this keeps Node off the instance entirely.

```bash
cd apps/console/web && npm ci && npm run build && cd ../../..
```

**Verify:** `ls apps/console/web/dist/index.html` exists.

## Step 5. Ship the repo

```bash
ssh $INSTANCE 'sudo mkdir -p /opt/ams-s3-demo && sudo chown ubuntu:ubuntu /opt/ams-s3-demo'

rsync -av --exclude .venv --exclude 'apps/console/web/node_modules' \
  ./ "$INSTANCE:/opt/ams-s3-demo/"
```

> **Do not exclude `.git`.** `demo/reset_s3.sh` and `demo/reset_s3_endorsement.sh`
> restore the pre-CR baseline with `git checkout HEAD -- <paths>` (**not** from the
> `s3-baseline` / `s3-endorsement-baseline` tags — those predate this layout and
> restoring from them breaks reseeding with an unrecoverable FOREIGN KEY error).
> Without a working checkout, reset fails and you cannot re-run the demo a second
> time. Ship the commit you intend to demo, not a dirty tree — see the warning
> under Step 12.

**Verify:**

```bash
ssh $INSTANCE 'cd /opt/ams-s3-demo && git rev-parse --short HEAD && git status --porcelain | head && ls apps/console/web/dist/index.html'
```

You want the commit you intended, a clean status, and the dist file present.

## Step 6. Create the environment file

```bash
ssh $INSTANCE 'cat > /opt/ams-s3-demo/.env' <<EOF
LLM_PROVIDER=bedrock
AWS_REGION=$AWS_REGION
BEDROCK_MODEL=anthropic.claude-sonnet-5

# Recorded outputs are primary for the demo (CLAUDE.md demo-reliability rule).
LLM_MODE=replay

# GITLAB_MODE defaults to "live". Left unset, the pipeline tries to reach GitLab
# from inside the locked-down VPC and hangs mid-beat.
GITLAB_MODE=replay
JIRA_MODE=replay
SN_MODE=mock
EOF
```

Set `BEDROCK_MODEL` to the exact id you confirmed in Step 1. Keep the
`anthropic.` prefix — the bare first-party id (`claude-sonnet-5`) returns a 400
on Bedrock.

**Verify:** `ssh $INSTANCE 'cat /opt/ams-s3-demo/.env'`

---

# Part C — Provision

## Step 7. Run the bootstrap script

Installs system packages, creates the venv, installs pinned requirements,
installs the two systemd units and the nginx config, and starts everything.
It is idempotent — safe to re-run after a code update.

```bash
ssh $INSTANCE 'sudo bash /opt/ams-s3-demo/deploy/aws/bootstrap.sh'
```

**Verify:**

```bash
ssh $INSTANCE 'curl -fsS http://localhost/api/health'   # -> {"ok":true}
```

## Step 8. Check both services are up

```bash
ssh $INSTANCE 'systemctl is-active ams-s3-console ams-s3-mockapp nginx'
```

Expect `active` three times. If not:
`ssh $INSTANCE 'journalctl -u ams-s3-console -n 50 --no-pager'`

---

# Part D — Verify it actually works

## Step 9. Prove Bedrock works end to end

Everything so far can pass with Bedrock still misconfigured. This is the first
step that makes a **real** model call, bypassing the cache.

```bash
ssh $INSTANCE 'cd /opt/ams-s3-demo && sudo -u ubuntu env \
  PYTHONPATH=/opt/ams-s3-demo LLM_MODE=live LLM_NO_CACHE=1 \
  .venv/bin/python -c "
from common.llm import complete
print(complete(\"Reply with exactly: BEDROCK OK\"))
"'
```

**Expect:** `BEDROCK OK`.

Failures arrive wrapped by the retry layer, so the real cause is at the end of
the line:

```
LLMError: bedrock call failed after 3 attempts: Error code: <code> - {...}
```

Read the code and message inside the wrapper:

| Inside the wrapper | Cause and fix |
|---|---|
| `401 authentication_error` — "security token ... is invalid" | No usable AWS credentials. Instance profile not attached (Step 2); attach it, then reboot the instance |
| `403 AccessDeniedException` | Credentials work, but model access is not granted (Step 1) or the region is wrong |
| `400 ValidationException` | `BEDROCK_MODEL` is wrong, or missing the `anthropic.` prefix |
| `404` on the model id | Model id not available in this region — recheck the Step 1 output |
| Hang, then a connection error | No network route to Bedrock (Step 3) |

Note it retries 3 times before reporting, so a misconfiguration takes a few
seconds to surface.

## Step 10. Warm the LLM cache — do not skip

This is the step that silently ruins an otherwise-working demo.

Cache entries are keyed two different ways. A beat with a pinned `cache_key`
is provider-independent and travels. Every other entry is content-hashed on
`provider|model|system|prompt`, so a cache warmed on a laptop against the
direct Anthropic API is a **guaranteed miss under Bedrock** — the provider and
model are part of the key.

Unwarmed, those beats make live Bedrock calls during the demo: real latency and
real spend, on beats you rehearsed as instant.

`.cache/llm/` is also gitignored, so it never arrives via rsync — and
`demo/reset_s3.sh` deletes it. **Warm after every reset, on the instance,
with the Bedrock environment active.**

```bash
ssh $INSTANCE 'cd /opt/ams-s3-demo && sudo -u ubuntu env \
  $(grep -v "^#" .env | grep -v "^$" | xargs) LLM_MODE=record \
  ./demo/warm_s3_cache.sh'
```

**Verify — the count is non-zero and matches what the same script produces
locally:**

```bash
ssh $INSTANCE 'ls /opt/ams-s3-demo/.cache/llm/*.json | wc -l'
```

## Step 11. Rehearse the whole demo on the instance

A rehearsal on a laptop against the direct Anthropic API does **not** exercise
the Bedrock path, the proxy, or the warmed cache. Do it here.

Open `http://<public-ip>/` and walk the full script in
`demo/DEMO_TEST_GUIDE.md`. Check the mockapp at
`http://<public-ip>/sl_policycore/` too.

Watch for any beat that pauses where rehearsal was instant — that is an
unwarmed cache entry going live. Re-run Step 10 if you see one.

---

# Part E — Demo day

## Step 12. Reset to a clean state

```bash
ssh $INSTANCE 'cd /opt/ams-s3-demo && sudo -u ubuntu ./demo/reset_s3.sh'
ssh $INSTANCE 'cd /opt/ams-s3-demo && sudo -u ubuntu ./demo/reset_s3_endorsement.sh'
ssh $INSTANCE 'cd /opt/ams-s3-demo && sudo -u ubuntu ./demo/reset_s3_claimsportal.sh'
ssh $INSTANCE 'cd /opt/ams-s3-demo && sudo -u ubuntu ./demo/reset_s3_enroldirect.sh'
```

Order matters: `reset_s3.sh` reseeds the database the amendment baseline builds
on, so it goes first.

All four scripts work. One pre-flight check is still worth doing, because it is
the one way Step 12 can fail on demo morning: the first two scripts restore
source with `git checkout HEAD -- repos/…`, so **the commit you deploy must
contain the target paths at their current location**. Deploy a commit from
before a target move (or a dirty tree whose move is uncommitted) and the
checkout has nothing to restore from. Confirm on the instance:

```bash
ssh $INSTANCE 'cd /opt/ams-s3-demo && git cat-file -e HEAD:repos/policycore/app.py && echo OK'
```

`reset_s3_claimsportal.sh` and `reset_s3_enroldirect.sh` restore by copying
their committed `.baseline/` snapshots, so they never depend on HEAD.

A manager can run the same resets from the console's `/admin` page instead of
over SSH — one explicit scope at a time, refused while the paths it would
overwrite are dirty, and reporting a missing-from-HEAD path as a named
`reset_blocked_reason` rather than a raw git error.

## Step 13. Re-warm, then restart

**Reset wipes `.cache/llm`.** Re-running Step 10 here is mandatory, not optional.

```bash
# re-warm (Step 10 command), then:
ssh $INSTANCE 'sudo systemctl restart ams-s3-console ams-s3-mockapp'
ssh $INSTANCE 'curl -fsS http://localhost/api/health'
```

The reset → warm → restart order matters. Warming before the reset is wasted.

---

# Reference

## Operating

```bash
sudo systemctl status  ams-s3-console ams-s3-mockapp
sudo systemctl restart ams-s3-console
sudo journalctl -u ams-s3-console -f
sudo journalctl -u ams-s3-mockapp -n 100 --no-pager
```

## Deploying a code update

```bash
cd apps/console/web && npm run build && cd ../../..    # if frontend changed
rsync -av --exclude .venv --exclude 'apps/console/web/node_modules' ./ "$INSTANCE:/opt/ams-s3-demo/"
ssh $INSTANCE 'sudo bash /opt/ams-s3-demo/deploy/aws/bootstrap.sh'
# then Step 10 (warm) if the cache was cleared
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `AccessDeniedException` from Bedrock | Model access not granted in the Bedrock console (Step 1), or wrong region |
| 400 on every LLM call | `BEDROCK_MODEL` missing the `anthropic.` prefix |
| Console 404s on every page | `apps/console/web/dist` not built or not shipped (Steps 4–5) |
| Mockapp stuck "connecting" | nginx missing websocket `Upgrade` headers, or `--server.baseUrlPath` not matching the location block |
| Pipeline hangs during analyze | `GITLAB_MODE` still `live` with no outbound route (Step 6) |
| `reset_s3.sh` fails: "pathspec did not match" | Deployed from a commit that predates a target move, so HEAD lacks the `repos/…` paths the script restores, or `.git` was excluded from the rsync (Steps 5, 12) |
| App restarts mid-codegen | `--reload` was added to the unit. Never use it: the pipeline writes `.py` files into the tree uvicorn would be watching |
| A rehearsed-instant beat now pauses | Unwarmed `.cache/llm` entry calling Bedrock live (Step 10) |

## Appendix A — why it is built this way

**One instance, one worker, no autoscaling.** The app is not stateless. The S3
pipeline writes generated `.py` files into its own working tree and shells out
to `pytest` (`api/routers/s3.py`, `s3_enhancement/testrun.py`). Local state that
must persist across requests includes the SQLite policy/claims DB
(`repos/policycore/core/db.py`), the ChromaDB vector directory (`common/vectorstore.py`),
the LLM replay cache, and `s3_enhancement/out/`. A second worker or instance
would serve inconsistent state mid-demo.

**No filesystem hardening in the systemd units.** `ProtectSystem=strict` and a
read-only root are deliberately absent — both break the core demo beat, which
requires writing into the application's own tree. The isolation boundary is the
instance and its security group, not the unit file.

**What runs where:**

| Process | Port | Unit | Serves |
|---|---|---|---|
| FastAPI console | 8000 (localhost) | `ams-s3-console` | `/api/*` and the built React SPA, including `/admin` |
| Streamlit PolicyCore | 8501 (localhost) | `ams-s3-mockapp` | MapleSure portal — the CR-2026-041/042 target |
| nginx | 80 (public) | `nginx` | `/` → console, `/sl_policycore/` → PolicyCore |

**Only two of the five processes are deployed.** ClaimsPortal's two services
(:8081, :8082) and EnrolDirect (:8083) have **no systemd unit and no nginx
location here** — this folder deploys the console and PolicyCore only. Units
for the ClaimsPortal pair existed once but were lost on 2026-07-28 while
uncommitted and are unrecoverable; nothing has been written for EnrolDirect.
Demoing CR-2026-043 or CR-2026-045 on EC2 means writing three units and three
`location` blocks first, modelled on the two that are here. Do not assume they
exist because the app does.

The console's `/admin` service controls are correspondingly limited on EC2:
they spawn a launch script and probe a port, which is not how a
systemd-managed process should be started or stopped. Use `systemctl` on the
instance.

## Appendix B — files in this directory

| File | Purpose |
|---|---|
| `bootstrap.sh` | Idempotent provisioning script (Step 7) |
| `ams-s3-console.service` | systemd unit for the FastAPI console |
| `ams-s3-mockapp.service` | systemd unit for the Streamlit PolicyCore portal |
| `nginx.conf` | Reverse proxy, long timeouts, SSE + websocket support |
| `bedrock-iam-policy.json` | Least-privilege Bedrock invoke policy (Step 2) |

That is the whole folder — there is nothing here for ClaimsPortal or
EnrolDirect, per the note above.

**Both units were updated on 2026-08-03 for the `repos/` layout.**
`ams-s3-mockapp.service` now runs `streamlit run repos/policycore/app.py`
(was `apps/policycore/app.py`); `ams-s3-console.service` is unchanged, since
the console did not move and still starts as
`uvicorn apps.console.api.main:app`. A `.service` file falls outside the
extension allowlist most path rewrites use, so it was missed on the first pass
of that move — check these two by hand after any future relayout.
