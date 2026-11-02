"""Second opinion for low-confidence characters from a vision LLM (DeepSeek, OpenAI-style API).

Only used when the PL template match is unsure.  The key lives in its own private
file (KEY_FILE, {"api_key": "..."}); it is never logged or returned to the GUI.
The model must answer one fixed JSON line, which is validated before use.
"""
import base64
import json
import os
import re
import urllib.request
from pathlib import Path

KEY_FILE = Path(os.environ.get('BRUSH_VISION_CLOUD_KEYFILE', '/home/xilinx/.config/so101/vision_cloud.local.json'))
ENDPOINT = 'https://api.deepseek.com/chat/completions'
MODEL = 'deepseek-flash'
STYLES = ('楷书', '行书', '草书', '隶书', '魏碑', '篆书', '其他')
PROMPT = ('图中是一个手写或毛笔书写的汉字。按格式回答：'
          '{"char":"单个简体汉字","style":"楷书|行书|草书|隶书|魏碑|篆书|其他","confidence":0到1的小数}')


def _key():
    try:
        data = json.loads(KEY_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    key = data.get('api_key') if isinstance(data, dict) else None
    return key.strip() if isinstance(key, str) and key.strip() else None


def available():
    return _key() is not None


def parse(text):
    """Validate the fixed one-line JSON answer; None if it does not conform."""
    match = re.search(r'\{.*\}', text or '', re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    ch, style, conf = data.get('char'), data.get('style'), data.get('confidence')
    if not isinstance(ch, str) or len(ch) != 1 or not '一' <= ch <= '鿿':
        return None
    if style not in STYLES:
        style = '其他'
    try:
        conf = max(0.0, min(1.0, float(conf)))
    except (TypeError, ValueError):
        conf = 0.0
    return dict(char=ch, style=style, confidence=conf)


def ask(png_bytes, timeout=10.0):
    """One character image -> dict(char, style, confidence) or None on any failure."""
    key = _key()
    if key is None:
        return None
    url = 'data:image/png;base64,' + base64.b64encode(png_bytes).decode()
    body = dict(model=MODEL, temperature=0, max_tokens=100, thinking={'type': 'disabled'},
                messages=[{'role': 'system', 'content': '你是汉字书法识别器。只输出一行JSON，不要解释。'},
                          {'role': 'user', 'content': [{'type': 'text', 'text': PROMPT},
                                                       {'type': 'image_url', 'image_url': {'url': url}}]}])
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as r:
            data = json.load(r)
        return parse(data['choices'][0]['message']['content'])
    except Exception:
        return None
