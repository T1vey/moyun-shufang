"""Portable image-to-image client for PC and PYNQ. Never logs credentials."""
import base64
import http.client
import io
import json
import os
import ssl
import sys
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

PROMPT_VERSION = 'plotter-sparse-v4'
# General part: sent with every subject (and with the phone's own text) so the result stays drawable.
PROMPT = '''将参考图重新设计成适合机械臂用笔绘制的极简「单线轮廓图标」。
目标是少量流畅、完整的长曲线，整图尽量控制在约 15～25 笔；保留辨识度，主动舍弃装饰细节。
纯白背景，居中留白。每条笔画都是单根实心黑线，粗细均匀，1024 像素画布上线宽约 4～6 像素。
线条本身不要再描边，不要空心双线，不要阴影、排线、纹理、上色和文字。
转弯平滑，自然相接处准确衔接；独立特征之间保留空白，不强行拉线串联；宁可省略，也不要用很多零碎短线。
画面风格是简练的钢丝轮廓示意图，不是写实素描、漫画上色页或精细插画。只输出图像。'''

# 细节模式的通用部分：不刻意压笔画，但写明这套系统能画出来的条件（单线、不填色、
# 线间距足够、无细碎闭环、总笔画有上限，避免超出规划帧数/节点预算）。
PROMPT_DETAIL = '''将参考图重新设计成适合机械臂用笔绘制的「单线线稿」，可以保留较多细节。
在保证每条线都能被笔画出来的前提下，尽量还原主体的结构和特征；线条数量不必刻意压缩，但整图一般不超过约 60 笔。
纯白背景，居中留白。每条笔画都是单根实心黑线，粗细均匀，1024 像素画布上线宽约 4～6 像素。
线条本身不要描边，不要空心双线；不要涂黑、填色、阴影、排线、网点和纹理，暗部和体积只用轮廓线表达。
相邻的线至少相隔约 12 像素，不要画成密集的平行线或交叉网格；不要细小闭环和碎点，短于约 20 像素的细节直接省略。
转弯平滑，相接处准确衔接。画面风格是干净的线描插画，不是素描、漫画上色页或写实插画。只输出图像。'''

GENERAL_PROMPTS = {'simple': PROMPT, 'detail': PROMPT_DETAIL}
DETAIL_NAMES = {'simple': '简略', 'detail': '细节'}


SUBJECT_PROMPTS = {
    'portrait': '''人像只画头部、颈部和肩部，保留参考人物的脸型、头部角度、发型外形和表情。
严格按以下极简分配：头发只用一条连续外轮廓加两条内部大弧线；脸颊下巴用一条流畅弧线；
每只眼睛只用一条简单弧线，每条眉毛一条弧线；鼻子一条曲线；微笑嘴巴一条弧线；
脖子两条线，肩部一条连贯轮廓。其余面部和衣服区域保持空白。
不要画阴影、排线、纹理、细小闭环、瞳孔、虹膜、睫毛、牙齿、嘴唇双轮廓、脸部皱纹、发丝、衣领、褶皱、徽章、头盔和手。
宁可省略小细节，也不要把一条曲线拆成很多零碎短线。''',
    'object': '''物体只保留主体的完整外轮廓，以及最多 2～4 条有辨识作用的内部结构线。
保留主体比例和自然的结构连接。删去背景、纹理、文字、花纹、重复装饰和小零件。
将细碎边缘概括为平滑长曲线，不添加新的物体。''',
    'landscape': '''画成山水风景，只画自然景物：画面中不出现人物、动物、建筑和文字。
用最少的长线概括：远山用一到两条连绵起伏的山脊线，近处山坡或岸线一条轮廓线；
水面用一到两条平缓的长弧线；可以加一个圆表示太阳或月亮，可以加一棵用三五笔概括的树或一叶小舟。
不要画云朵纹理、水波纹、树叶、草丛、石头皴法、倒影、阴影和排线，不要用短线堆砌细节。''',
}
# 细节模式下替换的主题部分（目前只有人物）；其余主题两种模式共用 SUBJECT_PROMPTS。
SUBJECT_PROMPTS_DETAIL = {
    'portrait': '''人像画头部到上半身，保留参考人物的脸型、头部角度、发型、表情和衣着特征。
可以画出：头发外轮廓和几组主要发丝走向（每组一条长线）、眉毛、眼睛的上眼睑和下眼睑、鼻梁和鼻翼、嘴唇轮廓、耳朵、脖子、衣领和衣服的几条主要褶皱。
每个特征都用单根线条勾出：眼睛用上下两条眼睑线，不必闭合成圈；瞳孔最多画一个小圆，不要涂黑。
不要涂黑头发或衣服，不要用排线表现阴影或发丝密度，不要画睫毛、皱纹、毛孔、细碎发丝、花纹和背景。
眼睛、鼻子、嘴巴这些小部位的线条要彼此分开、留出空白，避免挤成一团。''',
}

SUBJECT_NAMES = {'portrait': '人物', 'object': '物体', 'landscape': '山水风景', 'custom': '自定义'}
CUSTOM_MAX_CHARS = 200


def clean_custom(text):
    """Phone text: printable, single-spaced, at most CUSTOM_MAX_CHARS characters."""
    text = ''.join(ch if ch.isprintable() else ' ' for ch in str(text or ''))
    return ' '.join(text.split())[:CUSTOM_MAX_CHARS]


def build_prompt(subject='portrait', custom='', detail='simple'):
    """General part of the chosen mode + the subject, or + the phone's own description ('custom')."""
    if subject not in SUBJECT_NAMES:
        raise ValueError('选择人物、物体、山水风景或自定义')
    if detail not in GENERAL_PROMPTS:
        raise ValueError('选择简略或细节模式')
    general = GENERAL_PROMPTS[detail]
    if subject != 'custom':
        subject_prompt = SUBJECT_PROMPTS_DETAIL.get(subject) if detail == 'detail' else None
        return general + '\n' + (subject_prompt or SUBJECT_PROMPTS[subject])
    custom = clean_custom(custom)
    if not custom:
        raise ValueError('自定义模式请输入想画的内容')
    return (general + '\n画面内容按以下描述（只决定画什么）：' + custom +
            '\n描述与上面的线条要求冲突时，以线条要求为准：仍然只用单根黑色线条、纯白背景，不上色、不加阴影和排线。')


PROFILES = {'image2': 'cloud.auto-code.example.json',
            'image25-flare': 'cloud.flare.example.json',
            'image25-sunburst': 'cloud.sunburst.example.json',
            'seedream': 'cloud.seedream.example.json'}


def load_secrets(path):
    """Load a portable private-package file, never return or log its values."""
    values = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    allowed = {'SO101_IMAGE_API_KEY', 'SO101_ARK_API_KEY'}
    if not isinstance(values, dict) or set(values) - allowed:
        raise ValueError('私用密钥文件只支持 SO101_IMAGE_API_KEY / SO101_ARK_API_KEY')
    if any(not isinstance(v, str) or not v.strip() for v in values.values()):
        raise ValueError('私用密钥文件含空值或格式错误')
    for name, value in values.items():
        os.environ[name] = value.strip()


def profile_path(name):
    if name not in PROFILES:
        raise ValueError('未知图像模型配置')
    return Path(__file__).resolve().parent/'config'/PROFILES[name]


def load_config(path):
    if not path:
        raise ValueError('先在电脑配置 cloud.local.json，再用 --cloud-config 启动')
    cfg = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if cfg.get('protocol') not in ('image_json', 'image_edits'):
        raise ValueError('protocol 选择 image_json 或 image_edits，需与服务商文档匹配')
    parsed = urlsplit(cfg.get('endpoint', ''))
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.query:
        raise ValueError('endpoint 填写不带密钥和查询参数的完整 HTTPS 图片接口')
    if not isinstance(cfg.get('model'), str) or not cfg['model'].strip():
        raise ValueError('填写图生图模型名称')
    if not isinstance(cfg.get('extra', {}), dict) or set(cfg.get('extra', {})) & {'model','prompt','image','n'}:
        raise ValueError('extra 仅填写 size、response_format 等服务商参数')
    timeout = cfg.get('timeout_s', 180)
    if type(timeout) not in (int, float) or not 5 <= timeout <= 600:
        raise ValueError('timeout_s 范围为 5–600 秒')
    return cfg


def png_bytes(raw, max_edge=1536):
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(raw)) as source:
        if source.width*source.height > 16000000:
            raise ValueError('图片请压缩至 1600 万像素以内')
        if type(max_edge) is not int or not 256<=max_edge<=2048:
            raise ValueError('client_max_edge must be 256..2048')
        # Downsample before allocating multiple RGBA buffers on the 1 GB board.
        source.draft('RGB',(max_edge,max_edge))
        source.thumbnail((max_edge,max_edge))
        rgba = ImageOps.exif_transpose(source).convert('RGBA')
        bg = Image.new('RGBA', rgba.size, 'white'); bg.alpha_composite(rgba)
        rgb = bg.convert('RGB')
        out = io.BytesIO(); rgb.save(out, format='PNG')
        return out.getvalue()


def upload_bytes(raw, max_edge=1024):
    """Keep small RGB JPEGs intact; normalize other photos to bounded JPEG.

    Output line art still uses lossless PNG. Never apply this to generated art.
    Decode even passthrough inputs to reject truncated JPEG pixel streams.
    """
    from PIL import Image, ImageOps
    if type(max_edge) is not int or not 256 <= max_edge <= 2048:
        raise ValueError('client_max_edge must be 256..2048')
    with Image.open(io.BytesIO(raw)) as source:
        if source.width * source.height > 16000000:
            raise ValueError('图片请压缩至 1600 万像素以内')
        if getattr(source, 'n_frames', 1) != 1:
            raise ValueError('请选择一张静态图片')
        orientation = source.getexif().get(274, 1)
        if (source.format == 'JPEG' and source.mode == 'RGB' and
                max(source.size) <= max_edge and orientation == 1):
            source.load()
            return raw, 'image/jpeg'
        source.draft('RGB', (max_edge, max_edge))
        source.thumbnail((max_edge, max_edge))
        rgba = ImageOps.exif_transpose(source).convert('RGBA')
        background = Image.new('RGBA', rgba.size, 'white')
        background.alpha_composite(rgba)
        out = io.BytesIO()
        background.convert('RGB').save(out, format='JPEG', quality=90)
        return out.getvalue(), 'image/jpeg'


class ImageRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        old, new = urlsplit(request.full_url), urlsplit(newurl)
        if new.scheme != 'https' or new.username or new.password:
            raise ValueError('图像接口重定向必须使用 HTTPS')
        if request.has_header('Authorization') and (old.hostname, old.port) != (new.hostname, new.port):
            raise ValueError('图像接口重定向到不同站点；请配置正确端点')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class IncompleteImageResponse(ValueError):
    """A response ended early; safe to retry an image GET, never a generation POST."""


def read_response(response, limit):
    # HTTPResponse.read(amt) can silently return a short body at premature EOF.
    expected = None if getattr(response, 'chunked', False) else getattr(response, 'length', None)
    if isinstance(expected, int) and expected > limit:
        raise ValueError('服务商返回内容超过大小限制')
    raw = bytearray()
    while len(raw) <= limit:
        chunk = response.read(min(65536, limit + 1 - len(raw)))
        if not chunk:
            break
        raw.extend(chunk)
    if len(raw) > limit:
        raise ValueError('服务商返回内容超过大小限制')
    if isinstance(expected, int) and len(raw) != expected:
        raise IncompleteImageResponse('图像服务响应未完整接收，请检查网络后重试')
    return bytes(raw)


# Provider error codes are safe to show (no message text, account IDs or URLs are surfaced).
ERROR_HINTS = {
    'ModelNotOpen': '请在火山方舟控制台开通所选模型服务',
    'InputImageSensitiveContentDetected': '照片被判定为敏感内容，换一张照片再试',
    'InputTextSensitiveContentDetected': '提示词被判定为敏感内容，改一下自己写的内容再试',
    'OutputImageSensitiveContentDetected': '生成的图片被判定为敏感内容，换张照片或换个主题再试',
    'SensitiveContentDetected': '内容被判定为敏感，换张照片或改一下描述再试',
    'InvalidParameter': '请求参数不被接受（尺寸、格式或提示词）',
    'MissingParameter': '请求缺少必要参数',
    'AccountOverdueError': '账户欠费，请充值',
    'QuotaExceeded': '额度已用完',
    'RateLimitExceeded': '请求太频繁，稍后再试',
}


def error_message(status, code):
    code = code if isinstance(code, str) and code.replace('.', '').replace('_', '').isalnum() and len(code) <= 64 else None
    if code == 'ModelNotOpen':
        return 'ModelNotOpen：' + ERROR_HINTS[code]
    if code:
        hint = next((v for k, v in ERROR_HINTS.items() if code.startswith(k)), '检查端点、模型权限和余额')
        return '图像服务拒绝请求（HTTP %s，%s）：%s' % (status, code, hint)
    return '图像服务返回 HTTP %s；检查端点、模型权限和余额' % status


def fetch(request, timeout, limit):
    try:
        context = None
        if sys.platform == 'win32':
            import truststore
            context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), ImageRedirects())
        with opener.open(request, timeout=timeout) as response:
            return read_response(response, limit)
    except urllib.error.HTTPError as exc:
        # Surface only a known error code; never log provider messages/account IDs/URLs.
        try:
            code = json.loads(exc.read(8000)).get('error', {}).get('code')
        except Exception:
            code = None
        raise ValueError(error_message(exc.code, code)) from None
    except http.client.IncompleteRead:
        raise IncompleteImageResponse('图像服务响应未完整接收，请检查网络后重试') from None
    except http.client.HTTPException:
        raise ValueError('图像服务响应异常，请检查网络后重试') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError('图像服务连接失败或超时；检查网络、DNS 与系统时间') from None


def generate(raw, cfg, subject='portrait', transport=fetch, custom='', detail='simple'):
    total_started = time.perf_counter()
    prompt = build_prompt(subject, custom, detail)
    key = os.environ.get(cfg.get('api_key_env', 'SO101_IMAGE_API_KEY'), '').strip()
    if not key:
        raise ValueError('在电脑环境变量中设置 ' + cfg.get('api_key_env', 'SO101_IMAGE_API_KEY'))
    # Multipart compatibility is retained for providers requiring PNG edits.
    if cfg['protocol'] == 'image_json':
        original, upload_mime = upload_bytes(raw, cfg.get('client_max_edge', 1024))
    else:
        original, upload_mime = png_bytes(raw, cfg.get('client_max_edge',1536)), 'image/png'
    fields = dict(cfg.get('extra', {}), model=cfg['model'], prompt=prompt)
    if cfg.get('send_n', True):
        fields['n'] = 1
    if cfg['protocol'] == 'image_json':
        fields['image'] = 'data:'+upload_mime+';base64,'+base64.b64encode(original).decode('ascii')
        body = json.dumps(fields, separators=(',', ':')).encode()
        content_type = 'application/json'
    else:
        boundary = 'so101_'+uuid.uuid4().hex
        chunks = []
        for name, value in fields.items():
            if not name.replace('_', '').isalnum():
                raise ValueError('extra 字段名只能使用字母、数字和下划线')
            chunks.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' %
                           (boundary, name, value if isinstance(value, str) else json.dumps(value))).encode())
        chunks.extend([('--%s\r\nContent-Disposition: form-data; name="image"; filename="input.png"\r\nContent-Type: image/png\r\n\r\n' % boundary).encode(),
                       original, ('\r\n--%s--\r\n' % boundary).encode()])
        body = b''.join(chunks); content_type = 'multipart/form-data; boundary='+boundary
    request = urllib.request.Request(cfg['endpoint'], body, {'Authorization':'Bearer '+key, 'Content-Type':content_type}, method='POST')
    started = time.perf_counter()
    payload = transport(request, cfg.get('timeout_s', 180), 32000000)
    try:
        response = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError('图像服务返回的数据不完整或格式异常，请稍后重试；本次未保存线稿') from None
    api_s = time.perf_counter()-started
    if not isinstance(response, dict):
        raise ValueError('图像服务返回格式异常，未找到图片结果')
    entries = response.get('data')
    if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
        raise ValueError('接口未返回 data[0] 图片；需按服务商文档适配响应')
    item = entries[0]
    if item.get('b64_json'):
        try:
            image = base64.b64decode(item['b64_json'], validate=True)
        except Exception:
            raise ValueError('服务商返回了无效的图片编码') from None
    elif item.get('url'):
        parsed = urlsplit(item['url'])
        if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('图片下载地址必须是 HTTPS')
        # Retrying this GET downloads the same generated result; it never creates
        # or bills a second generation, and the provider key is not forwarded.
        for attempt in range(2):
            try:
                image = transport(urllib.request.Request(item['url']), 60, 24000000)
                break
            except IncompleteImageResponse:
                if attempt:
                    raise
    else:
        raise ValueError('未返回 b64_json 或 url 图片结果')
    from PIL import Image
    with Image.open(io.BytesIO(image)) as decoded:
        actual_size = list(decoded.size)
    output = png_bytes(image,cfg.get('client_max_edge',1536))
    return output, dict(model=cfg['model'], protocol=cfg['protocol'], subject=subject, prompt=prompt,
                        prompt_version=PROMPT_VERSION,
                        api_s=round(api_s, 3), total_s=round(time.perf_counter()-total_started, 3),
                        input_prepare_s=round(started-total_started, 3),
                        upload_bytes=len(original), upload_mime=upload_mime, request_bytes=len(body),
                        requested_size=cfg.get('extra', {}).get('size'), actual_size=actual_size)


class CloudJobs:
    def __init__(self, root, config_path=None):
        self.root = Path(root)/'cloud'; self.root.mkdir(exist_ok=True)
        self.config_path = config_path
        self.jobs = {}; self.lock = threading.Lock(); self.worker = None

    def profiles(self):
        return [dict(id=name, model=load_config(profile_path(name))['model']) for name in PROFILES]

    def start(self, raw, subject, profile=None):
        cfg = load_config(profile_path(profile) if profile else self.config_path)
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('已有线稿生成任务运行')
        jid = uuid.uuid4().hex
        job = dict(id=jid, status='RUNNING', model=cfg['model'], detail=cfg['model']+' 正在生成线稿')
        self.jobs[jid] = job
        def run():
            try:
                image, info = generate(raw, cfg, subject)
                folder = self.root/jid; folder.mkdir()
                (folder/'input.png').write_bytes(png_bytes(raw))
                (folder/'lineart.png').write_bytes(image)
                (folder/'generation.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
                job.update(status='DONE', detail='线稿已生成（%.1f 秒）；检查后点击提取轨迹' % info['total_s'], image='/cloud/'+jid+'/lineart.png')
            except Exception as exc:
                job.update(status='FAILED', detail=str(exc) if isinstance(exc, ValueError) else '线稿生成失败，请检查接口配置')
            finally:
                self.lock.release()
        self.worker = threading.Thread(target=run, daemon=True); self.worker.start()
        return dict(job)
