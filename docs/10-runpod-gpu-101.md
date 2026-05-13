# 10 - RunPod GPU 101

This guide is for the moment after you add credits and before you start typing
commands. The goal is to make the rented GPU feel less mysterious.

## The mental model

RunPod gives you a temporary remote computer.

Your laptop is still your laptop. The RunPod machine is somewhere else, with a
GPU attached. When you open a terminal in RunPod, you are typing commands inside
that remote computer, not on your Mac.

The GPU is useful because the slow/hot part of this project is local LLM
inference: asking a model like `mistral-small3.2:24b` to read ticket text and
return structured JSON. That is what heated your laptop. On RunPod, the GPU does
that work instead.

## What you are paying for

You are mostly paying for time while the pod is running.

In your screenshot, the RTX 4090 costs about `$0.69/hr`. With `$15`, that is:

```text
15 / 0.69 = about 21.7 hours
```

That is enough for setup, model download, a 250-ticket extraction, and a few
mistakes.

Downloads are not "extra paid API calls" in this workflow. You are not paying
OpenAI or Mistral per ticket. But downloads still happen while the pod is
running, so you are paying the pod's hourly rate during that time. Storage can
also cost a little if you keep a persistent volume after stopping the pod.

Simple rule: if the pod is running, money is slowly moving. If you are done,
stop it. If you have downloaded your results and do not need the machine
anymore, delete it.

## What you will see after deploying

After clicking Deploy, RunPod will create a pod. It may take a minute or two.
Then you usually get a Connect panel with options like:

- Web Terminal: a browser-based terminal.
- JupyterLab: file browser plus notebooks/terminal.
- SSH: terminal access from your own machine.

Use Web Terminal or JupyterLab Terminal. That is enough.

The terminal will look plain, probably something like:

```bash
root@something:/workspace#
```

That prompt means: "You are inside the rented machine. Type commands here."

## What happens in setup

These commands install basic tools:

```bash
apt-get update
apt-get install -y git curl
```

This copies your GitHub repo onto the rented machine:

```bash
git clone https://github.com/alikatgh/whats-users-want.git
cd whats-users-want
```

This creates and fills a Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

This may take time. It downloads Python packages like pandas, PyTorch,
sentence-transformers, Streamlit, and clustering libraries. That is normal.

## What Ollama is doing

Ollama is the local model runner. It lets the rented machine run the LLM without
sending ticket text to a paid API.

Install and start it:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve > ollama.log 2>&1 &
```

Then download the model:

```bash
ollama pull mistral-small3.2:24b
```

This model is large, around 15 GB. The download may take several minutes.
That is expected.

## Where your CSV goes

The GitHub repo does not include `data_2may.csv` because it is private support
data. You need to upload it to the RunPod machine.

Put it here:

```text
/workspace/whats-users-want/data_2may.csv
```

or, if your pod starts in `/root`:

```text
/root/whats-users-want/data_2may.csv
```

The important part is that when you are inside the repo folder, this command
should show the file:

```bash
ls -lh data_2may.csv
```

If it says "No such file", the pipeline cannot run yet.

## The run sequence

First activate Python and make the base analysis run:

```bash
source .venv/bin/activate

python scripts/option2_pipeline.py \
  --input data_2may.csv \
  --embedding-backend local \
  --embedding-model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

This creates a folder like:

```text
outputs/option2_20260512_123456/
```

Capture the latest folder name:

```bash
RUN_DIR=$(ls -td outputs/option2_* | head -1)
echo "$RUN_DIR"
```

Now run the expensive GPU part: local LLM extraction.

```bash
python scripts/llm_extract_rich_tickets.py "$RUN_DIR" \
  --backend ollama \
  --model mistral-small3.2:24b \
  --limit 1400 \
  --strategy risk_balanced
```

This asks the model to read the high-signal tickets first. This is the part we
rented the GPU for.

Then build the final user-wants taxonomy:

```bash
python scripts/build_user_wants_taxonomy.py "$RUN_DIR"
```

Then map the full cleaned corpus to that taxonomy:

```bash
python scripts/project_user_wants_full_corpus.py "$RUN_DIR"
```

## How to know it is working

During the LLM extraction, files should appear in the run folder:

```bash
ls -lh "$RUN_DIR" | grep extraction
```

You can also watch the JSONL row count grow:

```bash
wc -l "$RUN_DIR"/ollama_mistral-small3.2-24b_extractions.jsonl
```

If the number is increasing, the model is working.

## What to download at the end

Before deleting the pod, download the important outputs from `outputs/`.

Most useful files:

- `user_wants_taxonomy.csv`
- `user_wants_assignments.csv`
- `user_wants_workbook.xlsx`
- `user_wants_findings.md`
- `user_wants_all_assignments.csv`
- `user_wants_full_corpus_summary.csv`
- `user_wants_review_queue.csv`
- `user_wants_full_corpus_workbook.xlsx`
- `executive_findings.md`
- `option2_analysis_workbook.xlsx`
- `semantic_ticket_map.html`

If in doubt, download the whole latest run folder:

```text
outputs/option2_<timestamp>/
```

## The safety checklist

Before starting:

- You have `$15` credits.
- You selected a 24 GB GPU, such as RTX 4090.
- You can open Web Terminal or JupyterLab Terminal.
- You know how to upload `data_2may.csv`.

While running:

- Do not close the browser tab in panic; the pod keeps running.
- If a command is downloading packages, let it finish unless it is clearly stuck.
- If you are confused for more than 10 minutes, stop the pod and ask.

Before stopping/deleting:

- Download the output folder.
- Confirm the files are on your laptop.
- Stop the pod.
- Delete the pod/volume if you do not need the remote machine anymore.

## Important vocabulary

**Pod**: the rented remote computer.

**GPU**: the chip doing the heavy LLM work.

**Terminal**: the text box where you type commands.

**Container disk**: temporary disk attached to the pod. Usually disappears when
the pod is deleted.

**Volume / network volume**: persistent storage. Convenient, but can keep
charging after compute stops.

**Ollama**: local model runner. It lets the GPU run `mistral-small3.2:24b`.

**Model pull**: downloading the model weights. This is a large file download,
not a per-ticket API charge.

**Stop pod**: turns off compute billing, but persistent storage may remain.

**Delete pod**: removes the machine. Only do this after downloading outputs.
