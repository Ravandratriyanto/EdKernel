import json
import shutil
from pathlib import Path
ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / 'fixtures'
CURRICULA = ROOT / 'curricula' / 'demo'

def seed():
    (CURRICULA / 'reference').mkdir(parents=True, exist_ok=True)
    (CURRICULA / 'papers').mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / 'manifest.json', CURRICULA / 'manifest.json')
    shutil.copy(FIXTURES / 'topics.json', CURRICULA / 'topics.json')
    shutil.copy(FIXTURES / 'questions.json', CURRICULA / 'questions.json')
    shutil.copy(FIXTURES / 'reference.txt', CURRICULA / 'reference' / 'reference.txt')
    print('Demo curriculum seeded at curricula/demo/')
if __name__ == '__main__':
    seed()