import tempfile
from pathlib import Path
import cv2
import numpy as np
import core.vision.step_checker as sc

def _make_lines_page(n, h=600, w=800):
    img = np.full((h, w, 3), 255, np.uint8)
    for i in range(n):
        y = 120 + i * 130
        cv2.putText(img, f'working line {i + 1} here', (60, y), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 4)
    return img

def _write(img):
    path = Path(tempfile.mkdtemp()) / 'page.jpg'
    cv2.imwrite(str(path), img)
    return str(path)

def _line_index(name):
    return int(name.replace('step', '').replace('.jpg', ''))
LLM = dict(provider='fake', model='x', host='x', api_key='x', vision_model='x')

def test_finds_wrong_step():
    text = ['2x + 6 = 10', '2x = 4', 'x = 3']
    sc.transcribe = lambda b64, name='', **kw: text[_line_index(name)]
    sc.generate = lambda prompt, **kw: 'NO, x should be 2.' if 'x = 3' in prompt else 'YES'
    out = sc.check_working(_write(_make_lines_page(3)), **LLM)
    assert len(out['steps']) == 3, out['steps']
    assert out['error_index'] == 2, out['error_index']
    assert out['annotated'], 'no annotated image returned'
    print('  finds wrong step: OK')

def test_recapture_on_low_confidence():
    text = ['2x + 6 = 10', '2x = 4', 'x = 2']
    seen = {}

    def fake_transcribe(b64, name='', **kw):
        i = _line_index(name)
        seen[i] = seen.get(i, 0) + 1
        if i == 1 and seen[i] == 1:
            return ''
        return text[i]
    sc.transcribe = fake_transcribe
    sc.generate = lambda prompt, **kw: 'YES'
    out = sc.check_working(_write(_make_lines_page(3)), **LLM)
    assert seen.get(1, 0) == 2, 'line 2 was not re-read'
    assert any(('re-cropped' in t for t in out['trace'])), out['trace']
    assert out['error_index'] is None, out['error_index']
    print('  re-capture on low confidence: OK')

def main():
    print('step_checker isolated test(no LLM):')
    orig_t, orig_g = (sc.transcribe, sc.generate)
    try:
        test_finds_wrong_step()
        test_recapture_on_low_confidence()
        print('all passed')
    finally:
        sc.transcribe, sc.generate = (orig_t, orig_g)
if __name__ == '__main__':
    main()