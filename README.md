# Custom CXAS Slot-Filling UI

A standalone, glassmorphic themed **Slot-Filling & State Monitor UI** for Google Conversational Agents (CXAS). It provides real-time visualization of active tasks, filled slots, pending confirmations, and multi-channel switching (`MOBILE` vs `WEB`), completely decoupled from the underlying agent code.

---

## 🌐 Live Hosted Cloud Run Demos 

Click the link below to test the live Cloud Run visualizers directly in your browser:

| Demo Agent | Cloud Run Service | Live Public Demo Link | Try Typing |
| :--- | :--- | :--- | :--- |
| **Cashiering Agent** | `cxas-slot-visualizer` | 👉 **[https://cxas-slot-visualizer-357057401356.us-central1.run.app](https://cxas-slot-visualizer-357057401356.us-central1.run.app)** | `move money` → `online` → `ira` |


---

## ✨ Key Features for Demo Builders

1. **100% Schema-Agnostic Frontend (`webwidget-deploy.html`)**:
   - Dynamically renders any slot names returned by the backend (`transferType`, `symbol`, `claim_id`, `party_size`, etc.) inside the **Slot Values (Filled)** and **Pending Confirms** cards without hardcoding UI fields.
2. **Automatic DAG Schema Introspection (`server.py`)**:
   - Scans your agent's `tools/` folder at startup (`discover_agent_dag_slots`) for any `*_dag` or `dag_config` tool.
   - Automatically merges all slot definitions (`name`, `allowed_values`, `requires`, `type`) and extracts user slot values turn-by-turn without requiring custom regex extractors.
3. **Concurrent Multi-User Session Isolation**:
   - Every browser tab generates a unique `sessionId` (`sess_...`), isolating each viewer's conversation and slot state on the server.
4. **One-Command Google Cloud Run Deployment (`deploy_cloud_run.sh`)**:
   - Packages any target CXAS agent directory into a lightweight Python 3.11 container and deploys to Google Cloud Run in ~90 seconds.

---

## 🚀 How to Use This UI for Your Own CXAS Agent (3 Steps)

### Step 1: Clone or Copy this Folder
You can clone the repository:
```bash
git clone https://github.com/haneenaa007/cxas-slot-filling-ui.git
cd cxas-slot-filling-ui
```

Alternatively, copy the 4 core files into your workspace:
- `server.py` (Server code to run the CXAS agent)
- `webwidget-deploy.html` (Frontend UI)
- `Dockerfile` (Docker file to build the container)
- `deploy_cloud_run.sh` (One-click deployment script)

### Step 2: Test Locally with Your Agent
Point `--app-dir` to your CXAS agent directory and `--agent` to your root subagent name:

```bash
python3 server.py \
  --port 8085 \
  --app-dir "/path/to/your_cxas_agent_folder" \
  --agent "your_root_agent_name"
```

Open **`http://localhost:8085`** in your browser.

### Step 3: Deploy a Shareable Demo Link to Google Cloud Run
Run `./deploy_cloud_run.sh` with your GCP project, region, agent path, and agent name:

```bash
./deploy_cloud_run.sh \
  "your-gcp-project-id" \
  "us-central1" \
  "/path/to/your_cxas_agent_folder" \
  "your_root_agent_name"
```

What `deploy_cloud_run.sh` does automatically:
1. Copies your CXAS agent folder into `./cxas_agent` for container staging.
2. Builds and deploys the container to Google Cloud Run (`--allow-unauthenticated`).
3. Outputs a live `https://<service-name>-<hash>.us-central1.run.app` URL ready to share with your audience.

---

## How Automatic Slot Introspection Works

In production CXAS, `before_model_callback` evaluates the DAG using slots populated in `session_state`, while the LLM calls setter tools after each turn.

When running standalone in this visualizer:
1. **`discover_agent_dag_slots(app_dir, agent_name)`** inspects your agent's `tools/*_dag/python_code.py` or `tools/dag_config/python_code.py` files to read the declarative slot schema:
   ```json
   {
     "name": "alert_price_type",
     "allowed_values": ["bid", "ask", "last"],
     "requires": ["symbol"]
   }
   ```
2. **`auto_introspect_dag_and_extract_slots(...)`** checks which prerequisite `requires` slots are already filled, matches the user's message against `allowed_values` (or open-ended symbol/price patterns), and populates `state["sm"]["filled"]` automatically.
