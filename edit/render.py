import subprocess, sys, math, os
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

S = os.path.dirname(os.path.abspath(__file__))
V = S + '/dl/v/'
I = S + '/dl/img/'
AUDIO = '/root/.claude/uploads/62bc846c-ac5e-5d9d-8492-e1f229c16b72/dea228f0-ssstik.io_1791554239751.mp3'
OUT = sys.argv[1] if len(sys.argv) > 1 else S + '/out.mp4'
W = H = 1080
FPS = 30
DUR = 12.45
M = 1.18  # margin for shake / rotate
SW = int(W * M) // 2 * 2
rng = np.random.default_rng(7)

KICKS = [0.19, 0.70, 1.18, 1.79, 2.30, 2.88, 3.37, 3.88, 4.55, 5.04, 7.22, 7.76, 8.24, 8.75, 9.26, 9.91, 10.43, 10.91, 11.42, 11.91]
HATS = [0.84, 1.32, 1.86, 2.14, 2.51, 2.83, 3.16, 3.67, 4.02, 4.67, 5.53, 6.20,
        7.36, 7.59, 8.03, 8.54, 8.71, 9.06, 9.22, 9.38, 10.05, 10.54, 11.59]

# (start, end, source, src_offset, speed, look, flags)
# source: video file, image file, or ('text', words)
SEG = [
    (0.00, 0.70, 'v17.mp4', 12.0, 1.0, 'cold', 'zoomin'),
    (0.70, 1.18, 'v4.mp4', 0.9, 1.0, 'mono', ''),
    (1.18, 1.79, 'i1.png', 0, 1.0, 'cold', 'kb_dev'),
    (1.79, 2.30, 'v9.mp4', 1.0, 1.4, 'mono', 'tilt'),
    (2.30, 2.88, 'v7.mp4', 2.6, 1.0, 'cold', ''),
    (2.88, 3.37, 'v16.mp4', 4.0, 1.2, 'warm', ''),
    (3.37, 3.88, 'v19.webm', 4.0, 1.5, 'cold', 'tilt'),
    (3.88, 4.55, 'v15.mp4', 0.5, 1.0, 'hue', ''),
    (4.55, 5.04, 'v17.mp4', 24.0, 1.0, 'warm', ''),
    (5.04, 5.53, 'v3.mp4', 3.6, 1.0, 'cold', 'echo'),
    # breakdown
    (5.53, 6.20, ('text', 'not your keys'), 0, 1, '', ''),
    (6.20, 6.69, ('text', 'not your coins'), 0, 1, '', ''),
    (6.69, 7.01, 'v17.mp4', 48.3, 0.35, 'bw', 'echo'),
    (7.01, 7.22, 'v17.mp4', 36.4, 0.35, 'bw', 'echo strobe'),
    # drop
    (7.22, 7.59, 'i2.png', 0, 1.0, 'cold', 'kb_dev'),
    (7.59, 7.76, 'v4.mp4', 1.5, 1.0, 'hue', ''),
    (7.76, 8.03, 'v16.mp4', 11.0, 1.0, 'warm', ''),
    (8.03, 8.24, 'v9.mp4', 3.5, 1.0, 'invert', ''),
    (8.24, 8.54, 'v17.mp4', 54.6, 1.0, 'cold', ''),
    (8.54, 8.75, 'i3.png', 0, 1.0, 'hue', 'kb_dev'),
    (8.75, 9.06, 'v7.mp4', 0.3, 1.5, 'cold', ''),
    (9.06, 9.26, 'v19.webm', 6.0, 1.0, 'hue', ''),
    (9.26, 9.62, 'v11.mp4', 2.0, 1.0, 'mono', 'tilt'),
    (9.62, 9.91, 'v3.mp4', 4.4, 1.0, 'cold', ''),
    (9.91, 10.43, 'v7.mp4', 3.0, 1.0, 'warm', ''),
    (10.43, 10.91, 'i4.png', 0, 1.0, 'cold', 'kb_dev'),
    (10.91, 11.42, 'v14.mp4', 26.6, 0.6, 'cold', 'echo'),
    (11.42, 11.91, 'v1.mp4', 1.0, 1.0, 'hue', 'tilt'),
    (11.91, DUR, ('text', 'LEDGER'), 0, 1, '', 'end'),
]

CAPTIONS = [  # (start, end, text) small subtitle overlay like refs
    (0.07, 0.70, 'cold wallet'),
    (2.30, 2.88, 'offline.'),
    (4.55, 5.04, 'no hacks'),
    (7.22, 7.59, 'NANO X'),
    (8.54, 8.75, 'FLEX'),
    (10.43, 10.91, 'GEN5'),
]

FONT = '/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf'
FONT2 = '/usr/share/fonts/opentype/inter/Inter-Bold.otf'


def cover(img, size):
    h, w = img.shape[:2]
    s = size / min(h, w)
    img = cv2.resize(img, (max(size, round(w * s)), max(size, round(h * s))), interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]
    y, x = (h - size) // 2, (w - size) // 2
    return img[y:y + size, x:x + size]


def load_video(name, off, dur, speed):
    need = dur * speed + 0.2
    cmd = ['ffmpeg', '-v', 'error', '-ss', str(off), '-t', str(need), '-i', V + name,
           '-vf', f'fps={FPS},scale={SW}:{SW}:force_original_aspect_ratio=increase,crop={SW}:{SW}',
           '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, SW, SW, 3)
    return fr


def load_still(name):
    im = cv2.imread(I + name)
    h, w = im.shape[:2]
    # crop to device on the right side
    side = int(h * 0.92)
    x0 = int(w * 0.80) - side // 2
    x0 = max(0, min(w - side, x0))
    y0 = (h - side) // 2
    return cv2.resize(im[y0:y0 + side, x0:x0 + side], (SW, SW), interpolation=cv2.INTER_CUBIC)


def text_frame(words, big=True):
    im = Image.new('RGB', (SW, SW), (0, 0, 0))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT if big else FONT2, 170 if big else 120)
    bb = d.textbbox((0, 0), words, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    x, y = (SW - tw) / 2 - bb[0], (SW - th) / 2 - bb[1]
    d.text((x, y), words, font=f, fill=(255, 255, 255))
    if big:  # ledger-style corner brackets
        x0, y0, x1, y1 = (SW - tw) / 2 - 70, (SW - th) / 2 - 55, (SW + tw) / 2 + 70, (SW + th) / 2 + 55
        L, w = 55, 14
        for cx, cy, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            d.line([(cx, cy), (cx + sx * L, cy)], fill=(255, 255, 255), width=w)
            d.line([(cx, cy), (cx, cy + sy * L)], fill=(255, 255, 255), width=w)
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def grade(img, look, t):
    f = img.astype(np.float32)
    if look == 'mono' or look == 'bw':
        g = f.mean(2, keepdims=True)
        f = np.repeat(g, 3, 2)
        if look == 'mono':
            f = f * np.array([1.05, 1.0, 0.92])  # slight cool tint (BGR)
    elif look == 'cold':
        f = f * np.array([1.12, 1.0, 0.88])
    elif look == 'warm':
        f = f * np.array([0.85, 0.98, 1.12])
    elif look == 'invert':
        f = 1 - f
    elif look == 'hue':
        hsv = cv2.cvtColor((np.clip(f, 0, 1) * 255).astype(np.uint8), cv2.COLOR_BGR2HSV)
        hsv[..., 0] = (hsv[..., 0].astype(int) + int(t * 220)) % 180
        hsv[..., 1] = np.clip(hsv[..., 1].astype(int) * 2 + 90, 0, 255)
        f = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR).astype(np.float32) / 255
        f = np.round(f * 5) / 5  # posterize
    # contrast s-curve
    f = np.clip(f, 0, 1)
    f = f * f * (3 - 2 * f) * 0.6 + f * 0.4
    return f


def env(t, events, decay):
    v = 0.0
    for e in events:
        if 0 <= t - e < 1.5:
            v = max(v, math.exp(-(t - e) * decay))
    return v


def last_event(t, events):
    p = [e for e in events if e <= t]
    return (t - p[-1]) if p else 9


def radial_blur(img, amount):
    if amount < 0.01:
        return img
    acc = img.copy()
    n = 6
    h, w = img.shape[:2]
    for i in range(1, n):
        s = 1 + amount * i / n
        Mx = cv2.getRotationMatrix2D((w / 2, h / 2), 0, s)
        acc += cv2.warpAffine(img, Mx, (w, h), borderMode=cv2.BORDER_REFLECT)
    return acc / n


def rgb_split(img, px):
    if px < 1:
        return img
    px = int(px)
    out = img.copy()
    out[..., 2] = np.roll(img[..., 2], px, axis=1)
    out[..., 0] = np.roll(img[..., 0], -px, axis=1)
    return out


yy, xx = np.mgrid[0:H, 0:W]
VIG = 1 - 0.32 * (((xx - W / 2) ** 2 + (yy - H / 2) ** 2) / (W / 2) ** 2) ** 1.6
VIG = np.clip(VIG, 0.45, 1)[..., None].astype(np.float32)

cache = {}
cuts = [s[0] for s in SEG]


def seg_src(i):
    if i in cache:
        return cache[i]
    st, en, src, off, sp, look, fl = SEG[i]
    if isinstance(src, tuple):
        fr = [text_frame(src[1], big=src[1] == 'LEDGER')]
    elif src.endswith('.png'):
        fr = [load_still(src)]
    else:
        fr = load_video(src, off, en - st, sp)
    cache[i] = fr
    return fr


def overlay_caption(img, text, t_in):
    im = Image.fromarray(cv2.cvtColor((np.clip(img, 0, 1) * 255).astype(np.uint8), cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT, 92)
    bb = d.textbbox((0, 0), text, font=f)
    x = (W - (bb[2] - bb[0])) / 2 - bb[0]
    y = H * 0.76
    d.text((x, y), text, font=f, fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR).astype(np.float32) / 255


proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}',
                         '-r', str(FPS), '-i', '-', '-i', AUDIO, '-map', '0:v', '-map', '1:a',
                         '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-pix_fmt', 'yuv420p',
                         '-c:a', 'aac', '-b:a', '192k', '-t', str(DUR), '-movflags', '+faststart', OUT],
                        stdin=subprocess.PIPE)
prev = None
nfr = int(DUR * FPS)
shake_phase = rng.uniform(0, 100, 4)
for n in range(nfr):
    t = n / FPS
    i = max(k for k, c in enumerate(cuts) if c <= t + 1e-6)
    st, en, src, off, sp, look, fl = SEG[i]
    lt = t - st
    frames = seg_src(i)
    if len(frames) == 1:
        base = frames[0]
    else:
        idx = int(lt * sp * FPS)
        # velocity ramp: fast in, slow out
        if sp >= 1.0 and 'tilt' not in fl:
            idx = int((1 - math.exp(-lt * 6)) / 6 * FPS * 2.2 * sp + lt * sp * FPS * 0.5)
        base = frames[min(idx, len(frames) - 1)]
    img = base.astype(np.float32) / 255
    is_text = isinstance(src, tuple)
    drop = t >= 7.22 and t < 11.91

    # --- camera ---
    tc = lt
    k_env = env(t, KICKS, 9)
    h_env = env(t, HATS, 14)
    punch = 0.22 * math.exp(-tc * 10) if not is_text else 0.08 * math.exp(-tc * 8)
    zoom = 1 + punch + 0.06 * k_env
    if 'zoomin' in fl or 'kb_dev' in fl:
        zoom += 0.25 * (tc / max(en - st, 0.1))
    amp = (34 if drop else 20) * k_env + 10 * h_env
    if 5.53 <= t < 7.22:
        amp = 6 + 22 * max(0, (t - 6.69) / 0.53)  # tension build before the drop
    dx = amp * (math.sin(t * 61 + shake_phase[0]) + 0.5 * math.sin(t * 137 + shake_phase[1]))
    dy = amp * (math.cos(t * 53 + shake_phase[2]) + 0.5 * math.sin(t * 149 + shake_phase[3]))
    rot = (4 if drop else 2) * k_env * math.sin(t * 40)
    if 'tilt' in fl:
        rot += 9 * math.sin(tc * 5) * (1 - math.exp(-tc * 6))
    if not is_text:
        Mx = cv2.getRotationMatrix2D((SW / 2, SW / 2), rot, zoom / M * M)
        Mx[0, 2] += dx - (SW - W) / 2
        Mx[1, 2] += dy - (SW - H) / 2
        bm = cv2.BORDER_CONSTANT if 'tilt' in fl else cv2.BORDER_REFLECT
        img = cv2.warpAffine(img, Mx, (W, H), flags=cv2.INTER_LINEAR, borderMode=bm)
        img = grade(img, look, t)
    else:
        Mx = cv2.getRotationMatrix2D((SW / 2, SW / 2), rot * 0.5, zoom)
        Mx[0, 2] += dx * 0.6 - (SW - W) / 2
        Mx[1, 2] += dy * 0.6 - (SW - H) / 2
        img = cv2.warpAffine(img, Mx, (W, H), borderValue=0)

    # --- cut fx ---
    rb = 0.18 * math.exp(-tc * 18) + 0.06 * k_env * (1 if drop else 0.5)
    img = radial_blur(img, rb)
    img = rgb_split(img, (18 if drop else 10) * k_env + 6 * h_env)

    # echo / ghosting
    if 'echo' in fl and prev is not None:
        img = img * 0.55 + prev * 0.45
    elif prev is not None and tc < 2 / FPS and not is_text:
        img = img * 0.6 + prev * 0.4  # quick cross-ghost on the cut

    # strobe
    if 'strobe' in fl and (n % 2 == 0):
        img = img * 0.15
    # flash on first frame of drop + intro hit
    for ft, a in ((0.07, 1.0), (7.22, 1.0), (9.91, 0.7)):
        if 0 <= t - ft < 0.2:
            img = img + a * math.exp(-(t - ft) * 18)
    if drop and k_env > 0.85:
        img = img + 0.18

    # end text: glitch flicker + fade
    if 'end' in fl:
        if int(tc * FPS) % 5 == 1:
            img = rgb_split(img, 22)
        img *= max(0, min(1, (DUR - t) / 0.35))

    # post: vignette, grain, captions
    img = np.clip(img, 0, 1)
    if not is_text:
        img = img * VIG
    img = img + rng.normal(0, 0.035, (H, W, 1)).astype(np.float32)
    for cs, ce, ctext in CAPTIONS:
        if cs <= t < ce:
            img = overlay_caption(img, ctext, t - cs)
    img = np.clip(img, 0, 1)
    prev = img
    proc.stdin.write((img * 255).astype(np.uint8).tobytes())
    if n % 60 == 0:
        print(n, '/', nfr, flush=True)
proc.stdin.close()
proc.wait()
print('done', OUT)
