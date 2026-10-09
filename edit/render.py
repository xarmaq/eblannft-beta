"""Ledger jugg edit v4 — polished.

Motion only happens for a reason (a hit or a transition); no ambient jitter.
  * transitions across cuts: zoom-through (mirror tiles), whip-pan, spin, stretch, flash
  * eased impact shakes on kicks (keyframes every 2 frames, smoothstep in-betweens)
  * motion blur derived from real camera velocity (translate / rotate / zoom)
  * velocity speed ramps on footage (fast-in, slow, fast-out) with frame blending
  * lens bulge pulse + deep-glow pulse on kicks, 3D card swing, sharpen + CC
  * one-framers only on strong hits: flash, invert, rgb split, mosaic, hue
"""
import subprocess, sys, math, os
import numpy as np, cv2

S = os.path.dirname(os.path.abspath(__file__))
V = S + '/dl/v/'
I = S + '/dl/img/'
AUDIO = '/root/.claude/uploads/62bc846c-ac5e-5d9d-8492-e1f229c16b72/dea228f0-ssstik.io_1791554239751.mp3'
OUT = sys.argv[1] if len(sys.argv) > 1 else S + '/out4.mp4'
W = H = 1080
FPS = 30
DUR = 12.45
SW = 1300
SRC_FPS = 60  # footage is pulled at 60 fps so speed ramps have real in-betweens


def F(t):
    return int(round(t * FPS))


NFR = F(DUR)
KICK_A = [0.139, 0.662, 1.167, 1.834, 2.339, 2.844, 3.349, 3.849, 4.516, 5.021]
ROLL = [5.631, 5.747, 5.985, 6.113, 6.264, 6.409, 6.560, 6.658, 6.774, 6.966, 7.070]
DROP = 7.187
KICK_B = [7.187, 7.709, 8.214, 8.719, 9.218, 9.898, 10.391, 10.890, 11.389, 11.894]
SOFT = [0.789, 1.32, 2.51, 3.16, 3.67, 4.67, 7.36, 7.59, 7.976, 8.54, 9.334, 10.05, 10.507, 11.59]  # glow-only

C17 = (0.5, 0.44, 1.25)
# (src, offset, speed, look, crop, ramp, extra)
SHOTS = [
    ('v17.mp4', 0.2, 0.9, 'hot', (0.45, 0.42, 1.2), True, ''),
    ('v17.mp4', 11.0, 1.0, 'cold', C17, True, ''),
    ('v17.mp4', 26.9, 1.0, 'cold', (0.55, 0.45, 1.15), True, ''),
    ('v4.mp4', 0.7, 1.0, 'mono', None, True, ''),
    ('v7.mp4', 2.3, 1.0, 'cold', (0.5, 0.45, 1.3), True, ''),
    ('v17.mp4', 61.0, 1.0, 'cold', C17, True, 'swing'),
    ('v9.mp4', 0.8, 1.3, 'mono', None, True, ''),
    ('v17.mp4', 38.2, 1.0, 'gold', C17, True, ''),
    ('v16.mp4', 10.3, 1.3, 'warm', (0.5, 0.62, 1.0), True, 'swing'),
    ('v17.mp4', 52.3, 1.0, 'cold', C17, True, ''),
    # roll: hard cuts on every hit
    ('i1.png', 0, 1, 'bw', None, False, ''),
    ('v4.mp4', 1.6, 1, 'bwinv', None, False, ''),
    ('i3.png', 0, 1, 'bw', None, False, ''),
    ('v17.mp4', 27.4, 1, 'bwinv', (0.55, 0.45, 1.15), False, ''),
    ('i2.png', 0, 1, 'bw', None, False, ''),
    ('v19.webm', 5.0, 1, 'bwinv', None, False, ''),
    ('i4.png', 0, 1, 'bw', None, False, ''),
    ('v9.mp4', 3.0, 1, 'bwinv', None, False, ''),
    ('v11.mp4', 2.6, 1, 'bw', None, False, ''),
    ('v15.mp4', 1.0, 1, 'bwinv', None, False, ''),
    ('i1.png', 0, 1, 'bw', None, False, ''),
    # drop
    ('i1.png', 0, 1, 'cold', None, False, 'swing'),
    ('v19.webm', 3.8, 1.3, 'cold', None, True, ''),
    ('v3.mp4', 3.4, 1.2, 'cold', None, True, ''),
    ('v17.mp4', 56.8, 1.0, 'cycle', C17, True, ''),
    ('i3.png', 0, 1, 'mono', None, False, 'swing'),
    ('v11.mp4', 1.6, 1.0, 'mono', None, True, ''),
    ('v7.mp4', 0.3, 1.0, 'cold', (0.5, 0.5, 1.2), True, ''),
    ('v15.mp4', 0.5, 1.0, 'cold', None, True, 'swing'),
    ('i4.png', 0, 1, 'cold', None, False, ''),
    ('v17.mp4', 27.1, 0.5, 'mono', (0.55, 0.45, 1.15), False, ''),
]
cuts = [0.0] + KICK_A[1:] + ROLL + KICK_B + [DUR]
assert len(SHOTS) == len(cuts) - 1
CUTF = [F(c) for c in cuts]
END_SHOT = len(SHOTS) - 1
RF0, DF = F(ROLL[0]), F(DROP)

# transition into the shot that starts at each kick time
TRANS = {
    0.662: 'whipL', 1.167: 'zoom', 1.834: 'spin', 2.339: 'stretch', 2.844: 'whipU',
    3.349: 'zoom', 3.849: 'spinR', 4.516: 'whipR', 5.021: 'stretch',
    7.709: 'spin', 8.214: 'whipL', 8.719: 'zoom', 9.218: 'stretch', 9.898: 'spinR',
    10.391: 'whipU', 10.890: 'zoom', 11.389: 'whipR', 11.894: 'zoomout',
}
# impact shake per kick: (type, strength)
IMPACT = {
    0.139: ('slam', 0.8), 0.662: ('h', 0.5), 1.167: ('rot', 0.5), 1.834: ('slam', 0.7),
    2.339: ('h', 0.6), 2.844: ('rot', 0.6), 3.349: ('slam', 0.7), 3.849: ('h', 0.5),
    4.516: ('rot', 0.6), 5.021: ('slam', 0.9),
    7.187: ('slam', 1.8), 7.709: ('h', 1.0), 8.214: ('rot', 1.0), 8.719: ('slam', 1.1),
    9.218: ('h', 1.1), 9.898: ('slam', 1.3), 10.391: ('rot', 1.1), 10.890: ('h', 1.1),
    11.389: ('slam', 1.2), 11.894: ('rot', 0.6),
}
for j, t in enumerate(ROLL):
    IMPACT[t] = (['slam', 'h', 'rot'][j % 3], 0.35 + 0.6 * j / (len(ROLL) - 1))
# one-framers on strong hits only
OF = {
    0.139: ['flash'], 1.834: ['rgb'], 3.349: ['flash'], 5.021: ['rgb'],
    7.187: ['flash', 'rgb'], 7.709: ['hue'], 8.214: ['rgb'], 8.719: ['flash'],
    9.218: ['rgb'], 9.898: ['inv', 'rgb'], 10.391: ['rgb'], 10.890: ['flash'],
    11.389: ['mosaic', 'rgb'], 11.894: ['flash'],
}
for j, t in enumerate(ROLL):
    OF[t] = ['inv'] if j % 2 else ['flash']

N = NFR + 30
dx = np.zeros(N); dy = np.zeros(N); rot = np.zeros(N)
zm = np.ones(N); stx = np.ones(N); sty = np.ones(N); yaw = np.zeros(N)
bulge = np.zeros(N); glow = np.full(N, 0.08); fx = [[] for _ in range(N)]


def smooth(a, b, u):
    u = u * u * (3 - 2 * u)
    return a + (b - a) * u


def keyed(track, f0, keys, step=2, mode='add'):
    """keys sampled every `step` frames, smoothstep in-betweens."""
    for i in range((len(keys) - 1) * step + 1):
        k, r = divmod(i, step)
        v = keys[k] if k + 1 >= len(keys) else smooth(keys[k], keys[k + 1], r / step)
        if 0 <= f0 + i < N:
            if mode == 'add':
                track[f0 + i] += v
            else:
                track[f0 + i] *= v


W2 = W
# transitions (outgoing frames before the cut, incoming after)
for t, kind in TRANS.items():
    c = F(t)
    if kind.startswith('whip'):
        axis, sgn = {'whipL': (0, -1), 'whipR': (0, 1), 'whipU': (1, -1)}[kind]
        tr = dx if axis == 0 else dy
        for i, v in enumerate([0.06, 0.28, 0.72]):
            tr[c - 3 + i] += sgn * v * W2
        for i, v in enumerate([-0.62, -0.24, -0.07, -0.015]):
            tr[c + i] += sgn * v * W2
    elif kind == 'zoom':
        for i, v in enumerate([1.08, 1.32, 1.9]):
            zm[c - 3 + i] *= v
        for i, v in enumerate([0.55, 0.78, 0.92, 0.98]):
            zm[c + i] *= v
    elif kind == 'zoomout':
        for i, v in enumerate([0.94, 0.8, 0.6]):
            zm[c - 3 + i] *= v
        for i, v in enumerate([1.7, 1.3, 1.1, 1.03]):
            zm[c + i] *= v
    elif kind in ('spin', 'spinR'):
        sg = 1 if kind == 'spin' else -1
        for i, v in enumerate([6, 28, 72]):
            rot[c - 3 + i] += sg * v; zm[c - 3 + i] *= 1 + v / 400
        for i, v in enumerate([-68, -26, -7, -1.5]):
            rot[c + i] += sg * v; zm[c + i] *= 1 - v / 400
    elif kind == 'stretch':
        for i, v in enumerate([1.1, 1.45, 2.1]):
            stx[c - 3 + i] *= v; sty[c - 3 + i] *= 1 / v ** 0.25
        for i, v in enumerate([1.9, 1.35, 1.1, 1.02]):
            stx[c + i] *= v; sty[c + i] *= 1 / v ** 0.25

rng = np.random.default_rng(5)
for t, (typ, A) in IMPACT.items():
    c = F(t)
    s = rng.choice([-1, 1])
    decay = [1.0, -0.55, 0.28, -0.12, 0.04, 0.0]
    if typ == 'slam':
        keyed(dy, c, [A * 60 * v for v in decay])
        keyed(dx, c, [A * 18 * s * v for v in decay])
    elif typ == 'h':
        keyed(dx, c, [A * 60 * s * v for v in decay])
        keyed(dy, c, [A * 14 * v for v in decay])
    else:
        keyed(rot, c, [A * 6 * s * v for v in decay])
        keyed(dy, c, [A * 20 * v for v in decay])
    keyed(zm, c, [1 + A * 0.09, 1 + A * 0.03, 1.0], mode='mul')
    keyed(bulge, c, [0.22 * min(A, 1.4), 0.08 * min(A, 1.4), 0.0])
    keyed(glow, c, [0.35 * min(A, 1.4), 0.12, 0.0])
for t in SOFT:
    keyed(glow, F(t), [0.15, 0.05, 0.0])
for t, names in OF.items():
    c = F(t)
    for nm in names:
        for i in range(3 if nm == 'flash' else (1 if nm in ('inv', 'mosaic') else 2)):
            fx[c + i].append((nm, i))
# roll build: steady push-in (motivated by the riser), no random shake
for n in range(RF0, DF):
    g = (n - RF0) / (DF - RF0)
    zm[n] *= 1 + 0.35 * g * g
    bulge[n] += 0.1 * g
# drop: big push-out from the hit
keyed(zm, DF, [1.45, 1.18, 1.06, 1.0], mode='mul')
# 3D card swing on chosen shots (eased yaw that settles)
for k, sh in enumerate(SHOTS):
    if 'swing' in sh[6]:
        c0, c1 = CUTF[k], CUTF[k + 1]
        sg = 1 if k % 2 else -1
        for n in range(c0, c1):
            u = (n - c0) / max(c1 - c0, 1)
            yaw[n] += sg * (22 * (1 - u) ** 2 - 6 * u)
# outro: slow drift in
for n in range(CUTF[END_SHOT], NFR):
    zm[n] *= 1 + 0.12 * (n - CUTF[END_SHOT]) / (NFR - CUTF[END_SHOT])


# ---------------- sources ----------------
def ramp_times(nf, sp, ramp):
    """source seconds for each output frame of the shot (velocity curve)."""
    out, s = [], 0.0
    for i in range(nf):
        u = i / max(nf - 1, 1)
        v = (0.4 + 2.4 * math.exp(-u * 7) + 2.2 * max(0.0, u - 0.72) ** 2 * 12) if ramp else 1.0
        out.append(s)
        s += v * sp / FPS
    return out


def load_video(name, off, dur_s, crop):
    cx, cy, z = crop or (0.5, 0.5, 1.0)
    vf = (f"crop=w='min(iw,ih)/{z}':h='min(iw,ih)/{z}':"
          f"x='clip({cx}*iw-ow/2,0,iw-ow)':y='clip({cy}*ih-oh/2,0,ih-oh)',"
          f"scale={SW}:{SW},fps={SRC_FPS}")
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(off), '-t', str(dur_s + 0.3), '-i', V + name,
                          '-vf', vf, '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, SW, SW, 3)


def load_still(name):
    im = cv2.imread(I + name)
    h, w = im.shape[:2]
    side = int(h * 0.86)
    x0 = max(0, min(w - side, int(w * 0.84) - side // 2))
    y0 = (h - side) // 2
    return cv2.resize(im[y0:y0 + side, x0:x0 + side], (SW, SW), interpolation=cv2.INTER_CUBIC)[None]


cache = {}
PAD = 4  # frames rendered past each end for transitions


def shot_data(k):
    if k not in cache:
        src, off, sp, look, crop, ramp, extra = SHOTS[k]
        nf = CUTF[k + 1] - CUTF[k] + 2 * PAD
        if src.endswith('.png'):
            cache[k] = (load_still(src), None)
        else:
            ts = ramp_times(nf, sp, ramp)
            cache[k] = (load_video(src, max(0.0, off - PAD / FPS * sp), ts[-1] + 0.1, crop), ts)
    return cache[k]


def src_frame(k, n):
    fr, ts = shot_data(k)
    if ts is None:
        f = fr[0].astype(np.float32) / 255
        return np.clip((f - 0.5) * 1.15 + 0.42, 0, 1)
    li = n - CUTF[k] + PAD
    li = max(0, min(li, len(ts) - 1))
    if CUTF[k] >= RF0 and CUTF[k] < DF:  # roll: stutter (posterize time)
        li -= li % 2
    p = ts[li] * SRC_FPS
    i0 = int(p); a = p - i0
    i0 = min(i0, len(fr) - 1); i1 = min(i0 + 1, len(fr) - 1)
    f0 = fr[i0].astype(np.float32) / 255
    if a < 0.05 or i1 == i0:
        return f0
    return f0 * (1 - a) + fr[i1].astype(np.float32) / 255 * a


# ---------------- look ----------------
def hue_poster(f, shift):
    hsv = cv2.cvtColor((np.clip(f, 0, 1) * 255).astype(np.uint8), cv2.COLOR_BGR2HSV)
    hsv[..., 0] = (hsv[..., 0].astype(np.int32) + shift) % 180
    hsv[..., 1] = np.clip(hsv[..., 1].astype(np.int32) * 2.5 + 110, 0, 255)
    return np.round(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR).astype(np.float32) / 255 * 4) / 4


def grade(f, look, n):
    if look in ('mono', 'bw', 'bwinv'):
        g = f @ np.array([0.114, 0.587, 0.299], np.float32)
        f = np.repeat(g[..., None], 3, 2)
        if look == 'mono':
            f = f * np.array([1.05, 1.0, 0.94], np.float32)
        if look == 'bwinv':
            f = 1 - f
    elif look == 'cold':
        g = f.mean(2, keepdims=True)
        f = (g + (f - g) * 0.7) * np.array([1.1, 1.02, 0.9], np.float32)
    elif look == 'warm':
        f = f * np.array([0.86, 0.98, 1.1], np.float32)
    elif look == 'gold':
        f = f * np.array([0.74, 0.96, 1.15], np.float32)
    elif look == 'hot':
        f = f * np.array([0.8, 0.94, 1.15], np.float32)
    elif look == 'cycle':
        f = hue_poster(f, (n // 2) * 30)
    f = np.clip(f, 0, 1)
    f = f * f * (3 - 2 * f) * 0.65 + f * 0.35  # filmic contrast
    f = np.where(f > 0.7, 0.7 + (f - 0.7) * 0.55, f)  # highlight roll-off
    return f * 0.96 + 0.02  # gentle black lift


def sharpen(f, amt=0.55):
    b = cv2.GaussianBlur(f, (0, 0), 1.6)
    return f + (f - b) * amt


def deep_glow(f, s):
    hi = np.clip(f - 0.7, 0, 1)
    small = cv2.resize(hi, (W // 8, H // 8), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 6)
    mid = cv2.GaussianBlur(cv2.resize(hi, (W // 4, H // 4), interpolation=cv2.INTER_AREA), (0, 0), 3)
    g = cv2.resize(small, (W, H)) * 1.6 + cv2.resize(mid, (W, H)) * 0.9
    return f + g * s


yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
CX, CY = W / 2, H / 2
RX, RY = (xx - CX) / (W / 2), (yy - CY) / (H / 2)
R2 = np.clip(RX * RX + RY * RY, 0, 2).astype(np.float32)


def lens_bulge(f, k):
    if k < 0.01:
        return f
    sc = (1 - k * np.clip(1 - R2 / 2, 0, 1)).astype(np.float32)
    return cv2.remap(f, (CX + (xx - CX) * sc).astype(np.float32), (CY + (yy - CY) * sc).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def vec_blur(img, vx, vy):
    L = math.hypot(vx, vy)
    if L < 4:
        return img
    L = min(int(L), 161) | 1
    # blur at half res for speed on long kernels
    small = cv2.resize(img, (W // 2, H // 2), interpolation=cv2.INTER_AREA) if L > 31 else img
    Ls = (L // 2) | 1 if L > 31 else L
    k = np.zeros((Ls, Ls), np.float32)
    c = Ls // 2
    ux, uy = vx / math.hypot(vx, vy), vy / math.hypot(vx, vy)
    for i in range(Ls):
        s = i - c
        k[int(round(c + s * uy)), int(round(c + s * ux))] = 1
    out = cv2.filter2D(small, -1, k / k.sum(), borderType=cv2.BORDER_REFLECT)
    return cv2.resize(out, (W, H), interpolation=cv2.INTER_LINEAR) if L > 31 else out


def zoom_blur(img, amount, n=8):
    if amount < 0.01:
        return img
    acc = img.copy()
    for i in range(1, n):
        M = cv2.getRotationMatrix2D((CX, CY), 0, 1 + amount * i / n)
        acc += cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REFLECT)
    return acc / n


def spin_blur(img, deg, n=8):
    if abs(deg) < 1.2:
        return img
    acc = img.copy()
    for i in range(1, n):
        M = cv2.getRotationMatrix2D((CX, CY), deg * (i / n - 0.5), 1)
        acc += cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REFLECT)
    return acc / n


def rgb_split(img, px, ang):
    px = int(px)
    if px < 1:
        return img
    ddx, ddy = int(px * math.cos(ang)), int(px * math.sin(ang))
    out = img.copy()
    out[..., 2] = np.roll(img[..., 2], (ddy, ddx), axis=(0, 1))
    out[..., 0] = np.roll(img[..., 0], (-ddy, -ddx), axis=(0, 1))
    return out


def edge_aberration(img, amt):
    # lens-style chroma fringe growing toward the edges
    sc_r, sc_b = 1 + amt, 1 - amt
    out = img.copy()
    for ch, sc in ((2, sc_r), (0, sc_b)):
        M = cv2.getRotationMatrix2D((CX, CY), 0, sc)
        out[..., ch] = cv2.warpAffine(img[..., ch], M, (W, H), borderMode=cv2.BORDER_REFLECT)
    return out


def camera_matrix(n):
    R = cv2.getRotationMatrix2D((0, 0), rot[n], zm[n] * W / SW * 1.1)[:, :2]
    A2 = np.diag([stx[n], sty[n]]) @ R
    b = np.array([CX + dx[n], CY + dy[n]]) - A2 @ np.array([SW / 2, SW / 2])
    return np.hstack([A2, b[:, None]])


def yaw_warp(img, deg):
    if abs(deg) < 0.5:
        return img
    a = math.radians(deg)
    f = 1400.0
    pts = []
    for x, y in ((-CX, -CY), (CX, -CY), (CX, CY), (-CX, CY)):
        X, Z = x * math.cos(a), x * math.sin(a)
        s = f / (f + Z)
        pts.append((CX + X * s, CY + y * s))
    src = np.float32([(0, 0), (W, 0), (W, H), (0, H)])
    dst = np.float32(pts)
    # scale up so no edges show
    c = dst.mean(0)
    dst = (dst - c) * 1.12 + c
    P = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, P, (W, H), borderMode=cv2.BORDER_REFLECT)


VIG = np.clip(1 - 0.22 * (R2 / 2) ** 1.5 * 2, 0.6, 1)[..., None].astype(np.float32)

proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}',
                         '-r', str(FPS), '-i', '-', '-i', AUDIO, '-map', '0:v', '-map', '1:a',
                         '-c:v', 'libx264', '-preset', 'slow', '-b:v', '12M', '-maxrate', '16M', '-bufsize', '24M',
                         '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-t', str(DUR),
                         '-movflags', '+faststart', OUT], stdin=subprocess.PIPE)
CUTSET = set(CUTF)


def vel(track, n, log=False):
    g = (lambda v: math.log(v)) if log else (lambda v: v)
    if n in CUTSET:
        return g(track[n + 1]) - g(track[n])
    if n + 1 in CUTSET or n == 0:
        return g(track[n]) - g(track[max(n - 1, 0)])
    return (g(track[n + 1]) - g(track[n - 1])) / 2


for n in range(NFR):
    k = max(i for i, c in enumerate(CUTF[:-1]) if c <= n)
    li = n - CUTF[k]
    src, off, sp, look, crop, ramp, extra = SHOTS[k]
    img = grade(src_frame(k, n), look, n)
    img = sharpen(img)
    img = cv2.warpAffine(img, camera_matrix(n), (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    img = yaw_warp(img, yaw[n])

    # motion blur from camera velocity (shutter ~ 180deg)
    img = vec_blur(img, vel(dx, n) * 0.5, vel(dy, n) * 0.5)
    img = spin_blur(img, vel(rot, n) * 0.5)
    zv = abs(vel(zm, n, log=True))
    sv = abs(vel(stx, n, log=True))
    img = zoom_blur(img, zv * 0.5)
    if sv > 0.02:
        img = vec_blur(img, sv * 220, 0)

    img = lens_bulge(img, bulge[n])

    for nm, i in fx[n]:
        if nm == 'flash':
            img = img + [0.9, 0.45, 0.15][i]
        elif nm == 'inv':
            img = 1 - np.clip(img, 0, 1)
        elif nm == 'rgb':
            img = rgb_split(img, [26, 11][i] * (1.3 if n >= DF else 1.0), ang=(n * 1.7) % math.pi)
        elif nm == 'mosaic':
            sm = cv2.resize(img, (W // 30, H // 30), interpolation=cv2.INTER_AREA)
            img = cv2.resize(sm, (W, H), interpolation=cv2.INTER_NEAREST)
        elif nm == 'hue':
            img = hue_poster(img, 70 + 40 * i)

    if n == DF - 1:
        img = img * 0.0
    img = deep_glow(np.clip(img, 0, 1), glow[n])
    img = edge_aberration(img, 0.004 + 0.012 * min(bulge[n] * 4, 1))
    if k == END_SHOT:
        img = img * max(0.0, min(1.0, (NFR - n) / (0.6 * FPS)))
    img = np.clip(img, 0, 1) * VIG
    img = np.clip(img + rng.normal(0, 0.018, (H, W, 1)).astype(np.float32), 0, 1)
    proc.stdin.write((img * 255).astype(np.uint8).tobytes())
    if n % 75 == 0:
        print(n, '/', NFR, flush=True)
proc.stdin.close()
proc.wait()
print('done', OUT)
