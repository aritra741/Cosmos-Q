# Deploying COSMOS-Q on Alibaba Cloud

COSMOS-Q runs entirely on Alibaba Cloud infrastructure, provisioned as code.
No manual console configuration is required. This document is the single source
of truth for standing up the backend and verifying it end-to-end.

**Region:** `ap-southeast-1` (Singapore) — matches the Qwen Cloud international
endpoint `https://dashscope-intl.aliyuncs.com`.

## Architecture on Alibaba Cloud

| Layer | Alibaba Cloud Service | Provisioned by |
|---|---|---|
| Compute (MCP server) | ECS (Elastic Compute Service) | Terraform (built locally from source at boot) |
| Memory store | ApsaraDB RDS for PostgreSQL + pgvector | Terraform |
| Networking | VPC, VSwitch, Security Group | Terraform |
| Async maintenance (IAAF + ASC) | Function Compute (FC) | Serverless Devs (`s`) |

```
Internet ──► ECS (Docker: Build from source, run MCP server, :8765) ──► Qwen Cloud API
                          │
                          ▼
              ApsaraDB RDS (PostgreSQL 15 + pgvector)
                          ▲
                          │ (private VPC endpoint)
              Function Compute (cosmos-q-asc, daily 03:00 + on-demand)
```

## Prerequisites

Install locally:
- [Terraform](https://developer.hashicorp.com/terraform/downloads) >= 1.5
- [Docker](https://docs.docker.com/get-docker/) (only needed for local Function Compute build step)
- Serverless Devs: `npm install @serverless-devs/s -g`

Alibaba Cloud:
- A RAM user with permissions for **ECS, VPC, RDS, Function Compute**
- An AccessKey ID + Secret for that RAM user
- A DashScope (Qwen Cloud) API key
- A public Git repository containing the project codebase

## Environment Variables

Create a local, git-ignored `.env` file and export these before deploying. **Never commit them.**

```bash
export ALICLOUD_ACCESS_KEY="<ALICLOUD_ACCESS_KEY>"
export ALICLOUD_SECRET_KEY="<ALICLOUD_SECRET_KEY>"
export ALICLOUD_ACCOUNT_ID="<ACCOUNT_ID>"
export COSMOS_QWEN_API_KEY="<DASHSCOPE_API_KEY>"

# Mappings for Terraform variables
export TF_VAR_access_key="$ALICLOUD_ACCESS_KEY"
export TF_VAR_secret_key="$ALICLOUD_SECRET_KEY"
export TF_VAR_db_password="<STRONG_DB_PASSWORD>"
export TF_VAR_qwen_api_key="$COSMOS_QWEN_API_KEY"
export TF_VAR_git_repo_url="<YOUR_PUBLIC_GIT_REPO_URL>"

# Also needed by Serverless Devs (FC):
export COSMOS_PG_DSN=""        # filled in after Step 2 (from terraform output)
export COSMOS_QWEN_API_KEY="$COSMOS_QWEN_API_KEY"
export COSMOS_VPC_ID=""        # filled in after Step 2 (from terraform output)
export COSMOS_VSWITCH_ID=""    # filled in after Step 2 (from terraform output)
export COSMOS_SECURITY_GROUP_ID="" # filled in after Step 2 (from terraform output)
```

---

## Step 1 — Push Code to Remote Repository

Since the ECS instance clones the codebase directly from the Git URL specified in `TF_VAR_git_repo_url` at boot, **make sure your repository is public and updated with all changes before running Terraform.** 

---

## Step 2 — Provision Infrastructure with Terraform

```bash
cd infra
terraform init
terraform validate           # must succeed
terraform apply -auto-approve
```

**Record the outputs:**
```bash
terraform output
# mcp_public_ip = "x.x.x.x"
# mcp_url       = "http://x.x.x.x:8765"
# rds_endpoint  = "cosmosq....pg.rds.aliyuncs.com"
# vpc_id         = "vpc-xxx"
# vswitch_id     = "vsw-xxx"
# security_group_id = "sg-xxx"
```

Set the DSN and Networking vars for Function Compute (Step 5):
```bash
cd ..
export COSMOS_PG_DSN="postgresql://cosmos:${TF_VAR_db_password}@<rds_endpoint>:5432/cosmos_q"
export COSMOS_VPC_ID="<vpc_id>"
export COSMOS_VSWITCH_ID="<vswitch_id>"
export COSMOS_SECURITY_GROUP_ID="<security_group_id>"
```

> **Expected result:** `Apply complete! Resources: N added`. ECS, RDS, VPC, VSwitch, and Security Group are created.
> ECS is configured with a `depends_on = [alicloud_db_connection.cosmos]` block so that RDS connection endpoints exist before it boots.
> Allow 3–5 minutes for first-boot image compilation and server startup.

---

## Step 3 — Boot Progress Check and Troubleshooting

If the server doesn't respond or `/health` fails, SSH into the ECS instance. This is the **primary diagnostic checklist**:

```bash
ssh root@<mcp_public_ip>

# 1. Trail the cloud-init bootstrap log
tail -f /var/log/cosmos-bootstrap.log

# 2. Check if the database wait/vector extension registration failed.
# 3. Check if the git clone failed (e.g. repository is private or incorrect URL).
# 4. Check if the local docker build failed.
# 5. Check container logs
docker logs cosmos-q
```

---

## Step 4 — Early pgvector Extension Check

To verify managed pgvector loaded correctly, query PostgreSQL directly from inside the ECS instance (since RDS is private to the VPC, this cannot be run locally):

```bash
ssh root@<mcp_public_ip>

# Inside ECS:
PGPASSWORD='<STRONG_DB_PASSWORD>' psql -h <rds_endpoint> -U cosmos -d cosmos_q -c "SELECT extname FROM pg_extension WHERE extname='vector';"
```
**Expected Output:**
```
 extname 
---------
 vector
(1 row)
```

---

## Step 5 — Verify the MCP server and memory store

From your local machine:

```bash
MCP_URL=$(cd infra && terraform output -raw mcp_url)

# 5a. Liveness
curl -s $MCP_URL/health
# → {"status":"ok"}

# 5b. Tool discovery (expect 5 tools)
curl -s $MCP_URL/tools

# 5c. Store a memory
curl -s -X POST $MCP_URL/invoke -H 'Content-Type: application/json' -d '{
  "tool":"memory_store",
  "args":{"user_id":"test-user","content":"I use FastAPI and deploy on Alibaba Cloud ECS"}
}'

# 5d. Retrieve it (proves pgvector ANN search against RDS)
curl -s -X POST $MCP_URL/invoke -H 'Content-Type: application/json' -d '{
  "tool":"memory_retrieve",
  "args":{"user_id":"test-user","query":"what framework do I use?"}
}'
# → memory brief containing the FastAPI memory
```

---

## Step 6 — Deploy the Function Compute maintenance handler

Make sure you have exported:
- `COSMOS_PG_DSN`
- `COSMOS_QWEN_API_KEY`
- `COSMOS_VPC_ID`
- `COSMOS_VSWITCH_ID`
- `COSMOS_SECURITY_GROUP_ID`
- `ALICLOUD_ACCOUNT_ID`

```bash
# Build with Docker so Linux-native wheels (psycopg) are correct
s build --use-docker

# Deploy (reads s.yaml)
s deploy -y
```

**Verify:**
```bash
# Manual invoke against the live RDS (proves VPC binding works)
s invoke -e '{"user_id":"test-user","trigger":"manual"}'

s logs      # confirm IAAF + ASC executed, no DB connection errors
s info      # confirm timer trigger "daily-maintenance" enabled (cron 0 0 3 * * *)
```

> **If `s invoke` times out:** the FC function cannot reach RDS. Confirm
> `vpcConfig` in `s.yaml` references the VSwitch ID and Security Group ID from
> `terraform output`, and that the Security Group allows the function's traffic
> to RDS on port 5432.

---

## Step 7 — Verify the full cognitive lifecycle

```bash
MCP_URL=$(cd infra && terraform output -raw mcp_url)

# Contradict the stored preference → triggers RTR versioning
curl -s -X POST $MCP_URL/invoke -H 'Content-Type: application/json' -d '{
  "tool":"memory_reconsolidate",
  "args":{"user_id":"test-user","content":"Actually I switched to Django now"}
}'

# Inspect the version chain directly in RDS
ssh root@<mcp_public_ip>
PGPASSWORD='<STRONG_DB_PASSWORD>' psql -h <rds_endpoint> -U cosmos -d cosmos_q -c \
  "SELECT content, version, status FROM memories WHERE user_id='test-user' ORDER BY version;"
# → original: status=SUPERSEDED; new node: incremented version, status=ACTIVE
```
