"""Draws docs/architecture.png. Every box here should match the code -- re-check
core/vision/ and the ECS task definition before changing a label."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

fig, ax = plt.subplots(figsize=(14, 9.4))
ax.set_xlim(0, 14)
ax.set_ylim(0, 9.4)
ax.axis('off')
BG = '#0f1117'
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
C = {'aws': '#232F3E', 'ecs': '#1a2332', 'opencv': '#1a3a2a', 'agent': '#2a2a14', 'rag': '#1a2a3a',
     'llm': '#2a1a3a', 'user': '#1e2a1e', 'service': '#2a2218', 'ext': '#1a1a2e',
     'orange': '#FF9900', 'green': '#2dba4e', 'blue': '#4a90d9', 'purple': '#9b59b6',
     'teal': '#1abc9c', 'red': '#e74c3c', 'yellow': '#e6c84a', 'white': '#e8eaf0', 'grey': '#8892a4'}


def box(x, y, w, h, color, border, lw=1.5, radius=0.25):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f'round,pad=0,rounding_size={radius}',
                                facecolor=color, edgecolor=border, linewidth=lw))


def label(x, y, text, size=8, color=C['white'], ha='center', bold=False):
    ax.text(x, y, text, fontsize=size, color=color, ha=ha, va='center',
            fontweight='bold' if bold else 'normal', fontfamily='monospace')


def arrow(x1, y1, x2, y2, color, text=None, rad=0.0):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=1.5, connectionstyle=f'arc3,rad={rad}'))
    if text:
        label((x1 + x2) / 2 + 0.08, (y1 + y2) / 2, text, size=6.5, color=color, ha='left')


def panel(x, y, w, h, fill, border, title, lines, title_size=8.5):
    """A box with a bold title and (text, colour) lines listed under it."""
    box(x, y, w, h, fill, border, lw=1.4)
    label(x + w / 2, y + h - 0.25, title, size=title_size, bold=True, color=border)
    for i, (text, colour) in enumerate(lines):
        label(x + w / 2, y + h - 0.58 - i * 0.27, text, size=6.8, color=colour)


W, G = C['white'], C['grey']

# -- title --
label(7, 9.1, 'EdKernel — Architecture', size=15, bold=True, color=C['orange'])
label(7, 8.8, 'OpenCV AI Competition 2026 · Team Metis (solo) · as deployed 2026-10-23', size=8.5, color=G)

# -- users --
panel(0.4, 7.45, 2.4, 1.05, C['user'], C['green'], 'Student', [('browser / phone', G), ('photo of handwritten working', W)])
panel(3.1, 7.45, 2.4, 1.05, C['user'], C['teal'], 'Teacher', [('browser', G), ('misconception map, uploads', W)])
panel(5.8, 7.45, 2.4, 1.05, C['user'], C['yellow'], 'Developer', [('/dev/<key> panel', G), ('live chats, study data', W)])

# -- AWS cloud --
box(0.2, 0.25, 10.0, 7.0, C['aws'], C['orange'], lw=2.0, radius=0.4)
label(9.0, 7.02, 'AWS ap-southeast-1', size=8, bold=True, color=C['orange'])

box(0.5, 6.25, 9.4, 0.5, C['service'], C['orange'], lw=1.3, radius=0.15)
label(5.2, 6.5, 'Application Load Balancer  →  target group edkernel-tg  →  port 5000', size=7.5, color=W)
for x in (1.6, 4.3, 7.0):
    arrow(x, 7.45, x, 6.77, C['white'])

# -- ECS Fargate task --
box(0.5, 2.35, 9.4, 3.7, C['ecs'], C['blue'], lw=1.8, radius=0.3)
label(5.2, 5.85, 'ECS Fargate (x86) — Flask app, gunicorn 2 workers × 4 threads  ·  app.py + /v1/ API', size=8, bold=True, color=C['blue'])

# OpenCV pipeline -- names are the real functions in core/vision/
box(0.7, 2.5, 3.9, 3.1, C['opencv'], C['green'], lw=1.4)
label(2.65, 5.38, 'OpenCV 5 pipeline (deterministic)', size=8, bold=True, color=C['green'])
stages = [('find_page', 'bilateralFilter→Canny→approxPolyDP'),
          ('rectify  or  deskew', 'warpPerspective | minAreaRect→warpAffine'),
          ('binarise', 'adaptiveThreshold (Gaussian)'),
          ('segment', 'morphologyEx smear→findContours→merge'),
          ('crop + _upscale', 'resize line to 96 px → vision model')]
for i, (name, detail) in enumerate(stages):
    y = 5.05 - i * 0.5
    label(0.9, y, f'{i + 1}. {name}', size=7.2, bold=True, color=C['green'], ha='left')
    label(1.08, y - 0.21, detail, size=6.3, color=G, ha='left')

# agent loop -- check_working() in step_checker.py
panel(4.8, 2.5, 2.5, 3.1, C['agent'], C['yellow'], 'Agent loop',
      [('step_checker.py', G), ('read each line', W), ('unclear? re-crop', W), ('  wider + re-read', W),
       ('still? ask student', W), ('repeat line? skip', W), ('check i vs i-1', W), ('→ red box + trace', C['red'])],
      title_size=8)
arrow(4.6, 3.3, 4.8, 3.3, C['green'])

panel(7.5, 4.0, 2.2, 1.6, C['rag'], C['blue'], 'Socratic tutor',
      [('core/tutor.py', G), ('hint ladder', W), ('RAG: ChromaDB', W), ('top-k chunks', G)], title_size=8)
panel(7.5, 2.5, 2.2, 1.35, C['llm'], C['purple'], 'LLM client',
      [('core/llm/client.py', G), ('temp 0, timeout 60s', W), ('Groq | Bedrock', W)], title_size=8)
arrow(7.3, 3.2, 7.5, 3.2, C['yellow'])
arrow(8.6, 4.0, 8.6, 3.85, C['blue'])

# -- storage / ops row --
panel(0.5, 0.45, 3.6, 1.65, C['service'], '#e67e22', 'EFS (one file system)',
      [('users.db — SQLite (accounts, progress)', W), ('/app/.logs — session logs', W),
       ('/app/data/chroma — RAG index', W), ('survives task restarts', G)])
panel(4.3, 0.45, 2.1, 1.65, C['service'], C['orange'], 'ECR',
      [('edkernel:latest', W), ('built from repo', G), ('Dockerfile', G)])
panel(6.6, 0.45, 1.6, 1.65, C['service'], C['red'], 'CloudWatch',
      [('Logs', W), ('/ecs/edkernel', G)], title_size=8)
panel(8.4, 0.45, 1.6, 1.65, C['service'], C['orange'], 'Bedrock',
      [('adapter built', W), ('account on', C['red']), ('hold', C['red'])], title_size=8)
arrow(2.3, 2.35, 2.3, 2.1, '#e67e22')
arrow(5.35, 2.1, 5.35, 2.35, C['orange'])
arrow(7.4, 2.35, 7.4, 2.1, C['red'])
arrow(9.2, 2.5, 9.2, 2.1, C['purple'])

# -- outside AWS --
panel(10.6, 3.6, 3.1, 2.45, C['ext'], C['purple'], 'Groq API (live provider)',
      [('openai/gpt-oss-120b', W), ('tutor + step check', G), ('qwen/qwen3.8-27b', W), ('line transcription', G),
       ('free tier: 7k ITPM', C['red']), ('200k tokens/day', C['red'])])
arrow(9.7, 3.0, 10.6, 4.3, C['purple'], rad=-0.2)

panel(10.6, 0.45, 3.1, 2.8, C['ext'], C['teal'], 'Offline / separate',
      [('core/rag/ingest.py', W), ('builds the index once', G), ('per fresh EFS volume', G), ('', G),
       ('bench/ — OpenCV timings', W), ('on Graviton arm64 EC2', G), ('(not part of this deploy)', G)])

legend = [(C['green'], 'OpenCV 5'), (C['yellow'], 'agent decisions'), (C['blue'], 'app / RAG'),
          (C['purple'], 'LLM inference'), (C['orange'], 'AWS services')]
for i, (colour, text) in enumerate(legend):
    x = 0.4 + i * 2.75
    box(x, 0.0, 0.22, 0.18, colour, colour, lw=1, radius=0.04)
    label(x + 0.35, 0.09, text, size=7, color=G, ha='left')

plt.tight_layout(pad=0)
plt.savefig('docs/architecture.png', dpi=160, bbox_inches='tight', facecolor=BG)
print('Saved: docs/architecture.png')
