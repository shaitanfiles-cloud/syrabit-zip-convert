# Vertex AI Vector Search retriever (Task #608)

Syrabit's RAG layer can route nearest-neighbour calls through either:

| Backend     | Module                                | Default? |
|-------------|---------------------------------------|----------|
| Cloudflare Vectorize | `retrievers/vectorize.py`    | ✅ yes   |
| Google Vertex AI Vector Search | `retrievers/vertex.py` | A/B candidate |

Both implement `retrievers/base.Retriever`. Selection happens in
`retrievers/factory.py` — see [Toggling the active retriever](#toggling-the-active-retriever).

## 1. Provision the GCP resources

You only need to do this once per environment. Replace `<project>` and
`<region>` (we recommend `us-central1`).

```bash
# 1) Enable the API.
gcloud services enable aiplatform.googleapis.com --project <project>

# 2) Create the Index. Cosine metric matches our existing Vectorize
#    index so query scores are comparable.
gcloud ai indexes create \
    --project <project> --region <region> \
    --display-name syrabit-syllabus-v1 \
    --metadata-file index_metadata.json
```

`index_metadata.json`:

```json
{
  "config": {
    "dimensions": 1024,
    "approximateNeighborsCount": 50,
    "shardSize": "SHARD_SIZE_SMALL",
    "distanceMeasureType": "COSINE_DISTANCE",
    "algorithmConfig": {
      "treeAhConfig": {"leafNodeEmbeddingCount": 1000}
    }
  },
  "indexUpdateMethod": "STREAM_UPDATE"
}
```

`STREAM_UPDATE` is required so the ingestion script can call
`upsertDatapoints` directly. (Batch-update indexes need a Cloud Storage
staging area instead.)

```bash
# 3) Create an IndexEndpoint and deploy the Index to it.
gcloud ai index-endpoints create \
    --project <project> --region <region> \
    --display-name syrabit-syllabus-endpoint \
    --public-endpoint-enabled

gcloud ai index-endpoints deploy-index <ENDPOINT_ID> \
    --project <project> --region <region> \
    --deployed-index-id syrabit_syllabus_v1 \
    --index <INDEX_ID> \
    --display-name syrabit-syllabus-deployed \
    --machine-type e2-standard-2 \
    --min-replica-count 1 --max-replica-count 2
```

> Deployment takes 20–60 minutes. Capture the printed `INDEX_ID`,
> `ENDPOINT_ID`, and `DEPLOYED_INDEX_ID` — they map to the env vars
> below.

## 2. Service account

Create a least-privilege SA with roles
`roles/aiplatform.user` and `roles/aiplatform.indexEndpointAdmin`,
then download a JSON key. Paste the **entire JSON** into the
`VERTEX_SERVICE_ACCOUNT` secret (it is allowed to be a one-line JSON
string; the loader handles either inline JSON or a filesystem path).

## 3. Environment variables

Set these on Railway (or `.env` for local). Add them to the deployment
secret manager — the retriever silently disables itself if any are
missing, so a half-provisioned environment can never blackhole RAG.

```env
RAG_RETRIEVER=vectorize          # default; flip to "vertex" for full cutover
VERTEX_PROJECT_ID=my-gcp-project
VERTEX_LOCATION=us-central1
VERTEX_INDEX_ID=1234567890
VERTEX_INDEX_ENDPOINT_ID=1234567890
VERTEX_DEPLOYED_INDEX_ID=syrabit_syllabus_v1
VERTEX_SERVICE_ACCOUNT={"type":"service_account", …}   # one-line JSON
# Optional:
VERTEX_PUBLIC_DOMAIN_ENDPOINT=https://1234.us-central1-aiplatform.googleapis.com
VERTEX_DIMENSIONS=1024
```

## 4. Populate the index

Run on a worker that has Mongo + Vertex env vars set:

```bash
cd artifacts/syrabit-backend
python -m scripts.ingest_vertex_index --batch 50
```

Use `--limit 50 --dry-run` first to smoke-test embeddings without
writing anything to Vertex.

## 5. Toggling the active retriever

Two switches; the admin override wins:

* **Env var** (process-wide) — `RAG_RETRIEVER=vertex` and restart.
* **Admin runtime override** — `PUT /admin/retriever/config`
  with `{"active": "vertex"}`. The factory caches the override for 30
  seconds. Switching to a backend that reports `is_configured() == false`
  is rejected with HTTP 400 to prevent accidental outages.

Read the current state with `GET /admin/retriever/config` — it shows
the effective backend, the env value, the DB override, and per-backend
configuration status.

## 6. Compare backends

```bash
python -m bench.retriever_bench --top-k 10 --out bench/results/retriever_bench.json
```

The benchmark embeds each query with `vertex_services.embed_text`
(same path the live RAG uses) and runs the identical vector against
each configured retriever. Output reports p50/p95/p99 latency,
per-query top-k overlap (Jaccard + intersection-at-k as proxy recall),
and the percentage of queries that returned identical top-k sets.

## Roll-back

Cloudflare Vectorize stays the default and stays populated. To revert:

1. Set `RAG_RETRIEVER=vectorize` (or `PUT /admin/retriever/config
   {"active":"vectorize"}`).
2. Optionally undeploy the Vertex index to stop billing — the retriever
   will short-circuit on `is_configured()` once the env vars are
   cleared.
