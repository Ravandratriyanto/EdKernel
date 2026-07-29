# Training

Three phases, in order. Phase A teaches you the mechanics on a throwaway model.
Phase B collects the data Phase C needs. Do not skip B — you cannot go back and
log conversations that already happened.

---

## Phase A — build a transformer from scratch

`train_tiny.py` is a complete GPT in one file: tokenizer, model, training loop,
sampling. No `transformers`, no `Trainer`. Roughly 0.1–3M parameters depending
on flags, versus ~8,000M for the model you're calling on Groq.

It will never be a useful tutor. That is not the point. The point is that after
reading it, the Phase C commands stop being magic.

### Run it

```bash
pip install torch                 # CUDA build on the GPU box; the CPU wheel works too
python training/train_tiny.py     # ~15 min on CPU, ~1 min on any real GPU
```

Useful flags: `--iters`, `--n-layer`, `--n-embd`, `--block-size`, `--batch-size`,
`--device`, `--data mytext.txt`, `--sample-only --resume training/out/model.pt`.

### What to actually watch

The output line is `train`, `val`, and `gap`. **Watch val, not train.**

- **Both falling** — learning. Good.
- **Train falling, val flat or rising** — memorising the corpus instead of
  learning the pattern. This is overfitting, and it is the single most important
  thing to be able to recognise by eye. Provoke it deliberately:

  ```bash
  python training/train_tiny.py --data data/reference/biology.txt \
      --block-size 24 --iters 1500 --eval-every 300
  ```

  975 bytes is far too little data, and the split is unmistakable:

  ```
  step     0 | train 4.0151 | val 4.0223 | gap +0.0072
  step   600 | train 1.6035 | val 3.2071 | gap +1.6036  <- val rising: overfitting
  step  1500 | train 0.8975 | val 3.5887 | gap +2.6913  <- val rising: overfitting
  ```

  Train loss keeps dropping while val climbs — the model is memorising those 975
  bytes, not learning English. This is exactly the failure that will bite you in
  Phase C if you fine-tune on too few logged sessions, and it is why Phase B
  matters more than the GPU does.
- **Loss stuck near `ln(vocab_size)`** (≈4.17 for tinyshakespeare's 65 chars) —
  the model is predicting uniformly at random. Something is broken.
- **Loss going to NaN** — learning rate too high, or gradient clipping removed.

### Things worth doing to it

The file is meant to be edited. Each of these teaches something:

1. Set `--n-layer 1` vs `--n-layer 6`. Where does depth stop paying?
2. Delete `is_causal=True` in `CausalSelfAttention.forward`. Loss collapses to
   near zero and samples become garbage — the model is reading the answer.
3. Remove the `x +` residual connections in `Block.forward`, then try
   `--n-layer 8`. Watch a deep model fail to train at all.
4. Raise `--lr` to `1e-2`. Watch it diverge.
5. Change `temperature` in `show_sample` between 0.2 and 1.5. Low is repetitive,
   high is noise.

### Reading order

`CharTokenizer` → `get_batch` (see how x and y are offset by one) →
`TinyGPT.forward` → `CausalSelfAttention.forward` → the loop in `main`.

---

## Phase B — log real sessions

Not started. `/api/reply` currently discards every exchange. Fine-tuning needs
a few thousand real tutoring turns, and the app is already producing them.

Roughly twenty lines: append `{topic, messages, wrong_streak, correct}` as JSONL
on each turn. Do this before Phase C, and before you accumulate more unlogged use.

---

## Phase C — fine-tune a real model on that data

Not started. Blocked on Phase B having collected enough data.

Plan: take an open 7–8B base model, apply LoRA (or QLoRA if VRAM is tight),
train on the Phase B logs, export to GGUF, serve through Ollama — at which point
the `provider: ollama` path already in `llm/client.py` runs your own model with
no code changes.

VRAM, approximately:

| VRAM | What fits |
|------|-----------|
| 8–12 GB | QLoRA on 7B (4-bit) |
| 16–24 GB | LoRA on 7–8B in bf16, comfortably |
| 40 GB+ | full fine-tune of a 7B |

The goal is behaviour, not knowledge: a small model that is Socratic and speaks
plainly without needing the 2,300-character system prompt in `app.py`. Facts stay
in RAG, where they can be corrected without retraining.
