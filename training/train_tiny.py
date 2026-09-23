import argparse
import math
import os
import time
import torch
import torch.nn as nn
from torch.nn import functional as F

class CausalSelfAttention(nn.Module):

    def __init__(self, cfg):
        super().__init__()
        assert cfg.n_embd % cfg.n_head == 0
        self.qkv = nn.Linear(cfg.n_embd, 3 * cfg.n_embd, bias=False)
        self.proj = nn.Linear(cfg.n_embd, cfg.n_embd, bias=False)
        self.n_head = cfg.n_head
        self.dropout = cfg.dropout
        self.attn_drop = nn.Dropout(cfg.dropout)
        self.resid_drop = nn.Dropout(cfg.dropout)

    def forward(self, x):
        B, T, C = x.shape
        q, k, v = self.qkv(x).split(C, dim=2)
        head_dim = C // self.n_head
        q = q.view(B, T, self.n_head, head_dim).transpose(1, 2)
        k = k.view(B, T, self.n_head, head_dim).transpose(1, 2)
        v = v.view(B, T, self.n_head, head_dim).transpose(1, 2)
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True, dropout_p=self.dropout if self.training else 0.0)
        y = y.transpose(1, 2).contiguous().view(B, T, C)
        return self.resid_drop(self.proj(y))

class MLP(nn.Module):

    def __init__(self, cfg):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(cfg.n_embd, 4 * cfg.n_embd, bias=False), nn.GELU(), nn.Linear(4 * cfg.n_embd, cfg.n_embd, bias=False), nn.Dropout(cfg.dropout))

    def forward(self, x):
        return self.net(x)

class Block(nn.Module):

    def __init__(self, cfg):
        super().__init__()
        self.ln1 = nn.LayerNorm(cfg.n_embd)
        self.attn = CausalSelfAttention(cfg)
        self.ln2 = nn.LayerNorm(cfg.n_embd)
        self.mlp = MLP(cfg)

    def forward(self, x):
        x = x + self.attn(self.ln1(x))
        x = x + self.mlp(self.ln2(x))
        return x

class TinyGPT(nn.Module):

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.tok_emb = nn.Embedding(cfg.vocab_size, cfg.n_embd)
        self.pos_emb = nn.Embedding(cfg.block_size, cfg.n_embd)
        self.drop = nn.Dropout(cfg.dropout)
        self.blocks = nn.ModuleList([Block(cfg) for _ in range(cfg.n_layer)])
        self.ln_f = nn.LayerNorm(cfg.n_embd)
        self.head = nn.Linear(cfg.n_embd, cfg.vocab_size, bias=False)
        self.head.weight = self.tok_emb.weight
        self.apply(self._init_weights)

    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if module.bias is not None:
                nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(self, idx, targets=None):
        B, T = idx.shape
        assert T <= self.cfg.block_size, f'sequence of {T} exceeds block_size {self.cfg.block_size}'
        pos = torch.arange(T, device=idx.device)
        x = self.drop(self.tok_emb(idx) + self.pos_emb(pos))
        for block in self.blocks:
            x = block(x)
        logits = self.head(self.ln_f(x))
        if targets is None:
            return (logits, None)
        loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.reshape(-1))
        return (logits, loss)

    @torch.no_grad()
    def generate(self, idx, max_new_tokens, temperature=1.0, top_k=None):
        for _ in range(max_new_tokens):
            idx_cond = idx[:, -self.cfg.block_size:]
            logits, _ = self(idx_cond)
            logits = logits[:, -1, :] / temperature
            if top_k is not None:
                v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                logits[logits < v[:, [-1]]] = -float('inf')
            probs = F.softmax(logits, dim=-1)
            idx = torch.cat([idx, torch.multinomial(probs, num_samples=1)], dim=1)
        return idx

class CharTokenizer:

    def __init__(self, text):
        self.chars = sorted(set(text))
        self.stoi = {c: i for i, c in enumerate(self.chars)}
        self.itos = {i: c for i, c in enumerate(self.chars)}

    @property
    def vocab_size(self):
        return len(self.chars)

    def encode(self, s):
        return [self.stoi[c] for c in s if c in self.stoi]

    def decode(self, ids):
        return ''.join((self.itos[int(i)] for i in ids))

def get_batch(data, cfg, device):
    ix = torch.randint(len(data) - cfg.block_size - 1, (cfg.batch_size,))
    x = torch.stack([data[i:i + cfg.block_size] for i in ix])
    y = torch.stack([data[i + 1:i + cfg.block_size + 1] for i in ix])
    return (x.to(device), y.to(device))

@torch.no_grad()
def estimate_loss(model, splits, cfg, device, eval_iters):
    out = {}
    model.eval()
    for name, data in splits.items():
        losses = torch.zeros(eval_iters)
        for k in range(eval_iters):
            x, y = get_batch(data, cfg, device)
            _, loss = model(x, y)
            losses[k] = loss.item()
        out[name] = losses.mean().item()
    model.train()
    return out

def lr_at(step, cfg):
    if step < cfg.warmup:
        return cfg.lr * (step + 1) / cfg.warmup
    if step > cfg.iters:
        return cfg.lr * 0.1
    ratio = (step - cfg.warmup) / max(1, cfg.iters - cfg.warmup)
    return cfg.lr * 0.1 + 0.5 * (1 + math.cos(math.pi * ratio)) * (cfg.lr - cfg.lr * 0.1)

def main():
    p = argparse.ArgumentParser(description='Train a small GPT from scratch')
    p.add_argument('--data', default='training/data/tinyshakespeare.txt')
    p.add_argument('--out', default='training/out')
    p.add_argument('--resume', default='')
    p.add_argument('--sample-only', action='store_true')
    p.add_argument('--device', default='auto', choices=['auto', 'cuda', 'cpu'])
    p.add_argument('--iters', type=int, default=3000)
    p.add_argument('--batch-size', type=int, default=32)
    p.add_argument('--block-size', type=int, default=128, help='context length in characters')
    p.add_argument('--n-layer', type=int, default=4)
    p.add_argument('--n-head', type=int, default=4)
    p.add_argument('--n-embd', type=int, default=128)
    p.add_argument('--dropout', type=float, default=0.1)
    p.add_argument('--lr', type=float, default=0.0003)
    p.add_argument('--warmup', type=int, default=100)
    p.add_argument('--eval-every', type=int, default=250)
    p.add_argument('--eval-iters', type=int, default=50)
    p.add_argument('--compile', action='store_true', help='torch.compile (slow start, faster steps)')
    cfg = p.parse_args()
    device = ('cuda' if torch.cuda.is_available() else 'cpu') if cfg.device == 'auto' else cfg.device
    print(f'device: {device}' + (f' ({torch.cuda.get_device_name(0)})' if device == 'cuda' else ''))
    torch.manual_seed(1337)
    text = open(cfg.data, encoding='utf-8').read()
    tok = CharTokenizer(text)
    cfg.vocab_size = tok.vocab_size
    print(f'corpus: {len(text):,} chars | vocab: {tok.vocab_size} distinct characters')
    data = torch.tensor(tok.encode(text), dtype=torch.long)
    n = int(0.9 * len(data))
    splits = {'train': data[:n], 'val': data[n:]}
    for name, split in splits.items():
        if len(split) <= cfg.block_size + 1:
            raise SystemExit(f'--block-size {cfg.block_size} is too large for this corpus: the {name} split is only {len(split)} characters (it needs more than {cfg.block_size + 1}).\nTry --block-size {max(8, len(split) // 4)} or a bigger --data file.')
    model = TinyGPT(cfg).to(device)
    n_params = sum((p.numel() for p in model.parameters()))
    print(f'parameters: {n_params / 1000000.0:.2f}M')
    if cfg.resume:
        ckpt = torch.load(cfg.resume, map_location=device, weights_only=False)
        model.load_state_dict(ckpt['model'])
        tok.stoi, tok.itos = (ckpt['stoi'], ckpt['itos'])
        print(f'resumed from {cfg.resume}')
    if cfg.sample_only:
        show_sample(model, tok, device)
        return
    if cfg.compile:
        model = torch.compile(model)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, betas=(0.9, 0.95), weight_decay=0.1)
    os.makedirs(cfg.out, exist_ok=True)
    print(f'\ntraining for {cfg.iters} steps — watch val loss, not train loss\n')
    best_val = float('inf')
    t0 = time.time()
    for step in range(cfg.iters + 1):
        for group in opt.param_groups:
            group['lr'] = lr_at(step, cfg)
        if step % cfg.eval_every == 0:
            losses = estimate_loss(model, splits, cfg, device, cfg.eval_iters)
            gap = losses['val'] - losses['train']
            flag = '  <- val rising: overfitting' if losses['val'] > best_val and step > 0 else ''
            print(f"step {step:5d} | train {losses['train']:.4f} | val {losses['val']:.4f} | gap {gap:+.4f} | {time.time() - t0:5.1f}s{flag}")
            if losses['val'] < best_val:
                best_val = losses['val']
                torch.save({'model': getattr(model, '_orig_mod', model).state_dict(), 'cfg': vars(cfg), 'stoi': tok.stoi, 'itos': tok.itos}, os.path.join(cfg.out, 'model.pt'))
        x, y = get_batch(splits['train'], cfg, device)
        _, loss = model(x, y)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
    print(f'\nbest val loss: {best_val:.4f} | saved to {cfg.out}/model.pt')
    show_sample(getattr(model, '_orig_mod', model), tok, device)

def show_sample(model, tok, device, n_tokens=500):
    print('\n' + '─' * 60 + '\nsample\n' + '─' * 60)
    start = torch.zeros((1, 1), dtype=torch.long, device=device)
    out = model.generate(start, max_new_tokens=n_tokens, temperature=0.8, top_k=40)
    print(tok.decode(out[0].tolist()))
    print('─' * 60)
if __name__ == '__main__':
    main()