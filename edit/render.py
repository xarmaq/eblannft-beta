"""Ledger jugg edit v3.

Every hit gets its own camera move + one-framer instead of one generic shake:
  moves:  twitch (stepped low-fps jumps), slam (vertical impact), whip (side whip-pan),
          wobble (alternating rotation), zin / zout (zoom punch in / out with mirror edges),
          spin (90deg snap with mirrored tiles), stretch (squash/stretch), sshake (smooth build shake)
  one-framers: flash, black, inv, hblur, vblur, zblur, mosaic, hue, kaleido, rgb, mix, slices, thresh, ghost
Footage runs at 15 fps (frame doubled) like the refs; the drop switches to full 30 fps.
"""
import subprocess, sys, math, os
import numpy as np, cv2

S = os.path.dirname(os.path.abspath(__file__))
V = S + '/dl/v/'
I = S + '/dl/img/'
AUDIO = '/root/.claude/uploads/62bc846c-ac5e-5d9d-8492-e1f229c16b72/dea228f0-ssstik.io_1791554239751.mp3'
OUT = sys.argv[1] if len(sys.argv) > 1 else S + '/out3.mp4'
W = H = 1080
FPS = 30
DUR = 12.45
SW = 1300


def F(t):
    return int(round(t * FPS))


NFR = F(DUR)
KICK_A = [0.139, 0.662, 1.167, 1.834, 2.339, 2.844, 3.349, 3.849, 4.516, 5.021]
ROLL = [5.631, 5.747, 5.985, 6.113, 6.264, 6.409, 6.560, 6.658, 6.774, 6.966, 7.070]
DROP = 7.187
KICK_B = [7.187, 7.709, 8.214, 8.719, 9.218, 9.898, 10.391, 10.890, 11.389, 11.894]

C17 = (0.5, 0.44, 1.25)
SHOTS = [
    # groove
    ('v17.mp4', 0.2, 0.8, 'hot', (0.45, 0.42, 1.2)),
    ('v17.mp4', 11.0, 1.0, 'cold', C17),
    ('v17.mp4', 26.9, 1.0, 'cold', (0.55, 0.45, 1.15)),
    ('v4.mp4', 0.8, 1.0, 'mono', None),
    ('v7.mp4', 2.4, 1.0, 'cold', (0.5, 0.45, 1.3)),
    ('v17.mp4', 61.0, 1.0, 'cold', C17),
    ('v9.mp4', 1.0, 1.4, 'mono', None),
    ('v17.mp4', 38.3, 1.0, 'gold', C17),
    ('v16.mp4', 10.4, 1.3, 'warm', (0.5, 0.62, 1.0)),
    ('v17.mp4', 52.4, 1.0, 'cold', C17),
    # roll
    ('i1.png', 0, 1, 'bw', None),
    ('v4.mp4', 1.6, 1, 'bwinv', None),
    ('i3.png', 0, 1, 'bw', None),
    ('v17.mp4', 27.4, 1, 'bwinv', (0.55, 0.45, 1.15)),
    ('i2.png', 0, 1, 'bw', None),
    ('v19.webm', 5.0, 1, 'bwinv', None),
    ('i4.png', 0, 1, 'bw', None),
    ('v9.mp4', 3.0, 1, 'bwinv', None),
    ('v11.mp4', 2.6, 1, 'bw', None),
    ('v15.mp4', 1.0, 1, 'bwinv', None),
    ('i1.png', 0, 1, 'bw', None),
    # drop
    ('i1.png', 0, 1, 'cold', None),
    ('v19.webm', 4.0, 1.4, 'cold', None),
    ('v3.mp4', 3.6, 1.2, 'cold', None),
    ('v17.mp4', 57.0, 1.0, 'cycle', C17),
    ('i3.png', 0, 1, 'mono', None),
    ('v11.mp4', 1.8, 1.0, 'mono', None),
    ('v7.mp4', 0.4, 1.0, 'cycle', (0.5, 0.5, 1.2)),
    ('v15.mp4', 0.6, 1.0, 'cold', None),
    ('i4.png', 0, 1, 'cold', None),
    ('v17.mp4', 27.2, 0.45, 'mono', (0.55, 0.45, 1.15)),
]
cuts = [0.0] + KICK_A[1:] + ROLL + KICK_B + [DUR]
assert len(SHOTS) == len(cuts) - 1
CUTF = [F(c) for c in cuts]
END_SHOT = len(SHOTS) - 1

# (time, [moves], [one-framers], strength)
EV = [
    (0.139, ['zin', 'twitch'], ['flash', 'zblur'], 1.0),
    (0.380, ['twitch'], [], 0.4),
    (0.662, ['whip'], ['hblur'], 1.0),
    (0.840, ['twitch'], ['rgb'], 0.5),
    (1.167, ['spin'], ['zblur'], 1.0),
    (1.320, ['twitch'], ['mix'], 0.5),
    (1.834, ['slam'], ['inv'], 1.0),
    (2.140, ['twitch'], ['ghost'], 0.5),
    (2.339, ['zout'], ['mosaic'], 1.0),
    (2.510, ['stretch'], [], 0.5),
    (2.844, ['wobble'], ['rgb'], 1.0),
    (3.160, ['twitch'], ['vblur'], 0.6),
    (3.349, ['stretch', 'twitch'], ['flash'], 1.0),
    (3.670, ['twitch'], ['ghost'], 0.5),
    (3.849, ['zin'], ['hue'], 1.0),
    (4.020, ['twitch'], ['slices'], 0.5),
    (4.516, ['whip'], ['hblur'], 1.0),
    (4.670, ['twitch'], ['kaleido'], 0.5),
    (5.021, ['slam', 'twitch'], ['thresh'], 1.0),
    (5.340, ['twitch'], [], 0.5),
    # roll: each hit a different move, strength ramps up
    (5.631, ['spin'], ['inv'], 0.5),
    (5.747, ['twitch'], ['rgb'], 0.55),
    (5.985, ['zin'], ['zblur'], 0.6),
    (6.113, ['whip'], ['hblur'], 0.65),
    (6.264, ['slam'], ['kaleido'], 0.7),
    (6.409, ['wobble'], ['mosaic'], 0.75),
    (6.560, ['stretch'], ['inv'], 0.8),
    (6.658, ['twitch'], ['slices'], 0.85),
    (6.774, ['spin'], ['rgb'], 0.9),
    (6.966, ['zin'], ['thresh'], 0.95),
    (7.070, ['twitch', 'whip'], ['hblur'], 1.0),
    # drop
    (7.187, ['slam', 'zin', 'twitch'], ['flash', 'rgb', 'zblur'], 1.6),
    (7.360, ['twitch'], ['inv'], 0.7),
    (7.590, ['twitch'], ['hblur'], 0.6),
    (7.709, ['whip'], ['hue', 'hblur'], 1.2),
    (8.030, ['twitch'], ['mix'], 0.6),
    (8.214, ['spin'], ['zblur', 'rgb'], 1.2),
    (8.540, ['twitch'], ['mosaic'], 0.6),
    (8.719, ['zout', 'twitch'], ['kaleido'], 1.2),
    (9.060, ['twitch'], ['rgb'], 0.6),
    (9.218, ['stretch', 'slam'], ['flash'], 1.3),
    (9.380, ['twitch'], ['slices'], 0.6),
    (9.898, ['slam', 'twitch'], ['inv', 'rgb'], 1.3),
    (10.050, ['twitch'], ['ghost'], 0.6),
    (10.391, ['wobble'], ['hue'], 1.2),
    (10.540, ['twitch'], ['vblur'], 0.6),
    (10.890, ['whip'], ['thresh', 'hblur'], 1.2),
    (11.389, ['zin', 'twitch'], ['mosaic', 'rgb'], 1.3),
    (11.590, ['twitch'], ['ghost'], 0.6),
    (11.894, ['spin', 'sshake'], ['flash', 'zblur'], 0.8),
]

rng = np.random.default_rng(23)
# per-frame camera tracks
dx = np.zeros(NFR + 20); dy = np.zeros(NFR + 20); rot = np.zeros(NFR + 20)
zm = np.ones(NFR + 20); stx = np.ones(NFR + 20); sty = np.ones(NFR + 20)
ofx = [[] for _ in range(NFR + 20)]  # one-framer names per frame


def ease_out(x):
    return 1 - (1 - min(max(x, 0), 1)) ** 3


for t, moves, ofs, A in EV:
    f0 = F(t)
    sgn = rng.choice([-1, 1])
    for mv in moves:
        if mv == 'twitch':  # low fps: new random position every 2 frames
            for i in range(0, 10, 2):
                a = A * 55 * 0.62 ** (i // 2)
                ang = rng.uniform(0, 2 * math.pi)
                r = rng.uniform(-1, 1) * A * 3 * 0.6 ** (i // 2)
                for j in (0, 1):
                    dx[f0 + i + j] += a * math.cos(ang); dy[f0 + i + j] += a * math.sin(ang); rot[f0 + i + j] += r
        elif mv == 'slam':  # camera hits down, bounces up
            for i, v in enumerate([1.0, -0.55, 0.3, -0.15, 0.06]):
                dy[f0 + i] += A * 110 * v
                zm[f0 + i] *= 1 + A * 0.12 * abs(v)
        elif mv == 'whip':  # comes in from the side, overshoots, settles
            for i, v in enumerate([1.0, 0.45, -0.18, 0.07, -0.02]):
                dx[f0 + i] += sgn * A * 320 * v
                rot[f0 + i] += sgn * A * 3 * v
        elif mv == 'wobble':
            for i in range(9):
                rot[f0 + i] += (1 if i % 2 == 0 else -1) * sgn * A * 11 * 0.7 ** i
                zm[f0 + i] *= 1 + A * 0.14 * 0.7 ** i
        elif mv == 'zin':
            for i in range(7):
                zm[f0 + i] *= 1 + A * 0.42 * 0.55 ** i
        elif mv == 'zout':
            for i in range(7):
                zm[f0 + i] *= 1 - A * 0.32 * 0.55 ** i
        elif mv == 'spin':
            for i in range(7):
                rot[f0 + i] += sgn * 90 * (1 - ease_out((i + 1) / 6)) * min(A, 1.0) ** 0.3
                zm[f0 + i] *= 1 + 0.2 * (1 - ease_out((i + 1) / 6))
        elif mv == 'stretch':
            for i in range(6):
                k = 0.5 ** i
                stx[f0 + i] *= 1 + A * 0.55 * k
                sty[f0 + i] *= 1 - A * 0.18 * k
        elif mv == 'sshake':
            for i in range(16):
                a = A * 40 * (1 - i / 16)
                dx[f0 + i] += a * math.sin(i * 1.9); dy[f0 + i] += a * math.cos(i * 2.7)
    for of in ofs:
        n = 1 if of in ('inv', 'black', 'thresh') else 2
        if of in ('flash',):
            n = 3
        for i in range(n):
            ofx[f0 + i].append((of, i, A))

# constant choppy handheld (updated every 2 frames)
for n in range(0, NFR, 2):
    jx, jy = rng.normal(0, 3.0, 2)
    dx[n:n + 2] += jx; dy[n:n + 2] += jy
# roll: continuous push in + building smooth shake
rf0, df = F(ROLL[0]), F(DROP)
for n in range(rf0, df):
    g = (n - rf0) / (df - rf0)
    zm[n] *= 1 + 0.4 * g
    dx[n] += 18 * g * math.sin(n * 2.1); dy[n] += 18 * g * math.cos(n * 2.9)


# ---------------- sources ----------------
def load_video(name, off, frames_needed, speed, crop):
    cx, cy, z = crop or (0.5, 0.5, 1.0)
    need = frames_needed / FPS * speed + 0.3
    vf = (f"crop=w='min(iw,ih)/{z}':h='min(iw,ih)/{z}':"
          f"x='clip({cx}*iw-ow/2,0,iw-ow)':y='clip({cy}*ih-oh/2,0,ih-oh)',"
          f"scale={SW}:{SW},fps={FPS / speed}")
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(off), '-t', str(need), '-i', V + name,
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


def frames_for(k):
    if k not in cache:
        src, off, sp, look, crop = SHOTS[k]
        cache[k] = load_still(src) if src.endswith('.png') else load_video(src, off, CUTF[k + 1] - CUTF[k] + 4, sp, crop)
    return cache[k]


def src_frame(k, li, lowfps):
    fr = frames_for(k)
    if len(fr) == 1:
        return fr[0]
    if lowfps:
        li = (li // 2) * 2
    return fr[min(li, len(fr) - 1)]


# ---------------- looks ----------------
def grade(f, look, n):
    if look in ('mono', 'bw', 'bwinv'):
        g = f @ np.array([0.114, 0.587, 0.299], np.float32)
        f = np.repeat(g[..., None], 3, 2)
        if look == 'mono':
            f = f * np.array([1.06, 1.0, 0.93], np.float32)
        if look == 'bwinv':
            f = 1 - f
    elif look == 'cold':
        g = f.mean(2, keepdims=True)
        f = (g + (f - g) * 0.6) * np.array([1.12, 1.02, 0.86], np.float32)
    elif look == 'warm':
        f = f * np.array([0.82, 0.97, 1.12], np.float32)
    elif look == 'gold':
        f = f * np.array([0.7, 0.95, 1.18], np.float32)
    elif look == 'hot':
        f = f * np.array([0.75, 0.92, 1.2], np.float32)
    elif look == 'cycle':  # posterized palette cycling every 2 frames (ref 4 look)
        f = hue_poster(f, (n // 2) * 37)
    f = np.clip(f, 0, 1)
    return f * f * (3 - 2 * f) * 0.7 + f * 0.3


def hue_poster(f, shift):
    hsv = cv2.cvtColor((np.clip(f, 0, 1) * 255).astype(np.uint8), cv2.COLOR_BGR2HSV)
    hsv[..., 0] = (hsv[..., 0].astype(np.int32) + shift) % 180
    hsv[..., 1] = np.clip(hsv[..., 1].astype(np.int32) * 3 + 140, 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2].astype(np.int32) * 1.1 + 30, 0, 255)
    return np.round(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR).astype(np.float32) / 255 * 3) / 3


# ---------------- fx ----------------
def line_blur(img, L, horizontal):
    L = max(3, int(L) | 1)
    k = np.zeros((L, L), np.float32)
    if horizontal:
        k[L // 2, :] = 1
    else:
        k[:, L // 2] = 1
    return cv2.filter2D(img, -1, k / L, borderType=cv2.BORDER_REFLECT)


def vec_blur(img, vx, vy):
    L = math.hypot(vx, vy)
    if L < 4:
        return img
    L = min(int(L), 121) | 1
    k = np.zeros((L, L), np.float32)
    c = L // 2
    ux, uy = vx / math.hypot(vx, vy), vy / math.hypot(vx, vy)
    for i in range(L):
        s = i - c
        k[int(round(c + s * uy)), int(round(c + s * ux))] = 1
    return cv2.filter2D(img, -1, k / k.sum(), borderType=cv2.BORDER_REFLECT)


def zoom_blur(img, amount, n=7):
    if amount < 0.008:
        return img
    acc = img.copy()
    for i in range(1, n):
        M = cv2.getRotationMatrix2D((W / 2, H / 2), 0, 1 + amount * i / n)
        acc += cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REFLECT)
    return acc / n


def spin_blur(img, deg, n=6):
    if abs(deg) < 1.5:
        return img
    acc = img.copy()
    for i in range(1, n):
        M = cv2.getRotationMatrix2D((W / 2, H / 2), deg * i / n, 1)
        acc += cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REFLECT)
    return acc / n


def rgb_split(img, px, ang=0.0):
    px = int(px)
    if px < 1:
        return img
    ddx, ddy = int(px * math.cos(ang)), int(px * math.sin(ang))
    out = img.copy()
    out[..., 2] = np.roll(img[..., 2], (ddy, ddx), axis=(0, 1))
    out[..., 0] = np.roll(img[..., 0], (-ddy, -ddx), axis=(0, 1))
    return out


def mosaic(img, block):
    small = cv2.resize(img, (W // block, H // block), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (W, H), interpolation=cv2.INTER_NEAREST)


def slices(img, A):
    out = img.copy()
    y = 0
    while y < H:
        h = int(rng.integers(20, 140))
        if rng.random() < 0.55:
            out[y:y + h] = np.roll(img[y:y + h], int(rng.normal(0, 90 * A)), axis=1)
        y += h
    return out


def kaleido(img):
    out = img.copy()
    out[:, W // 2:] = img[:, :W // 2][:, ::-1]
    return out


yy, xx = np.mgrid[0:H, 0:W]
VIG = np.clip(1 - 0.3 * (((xx - W / 2) ** 2 + (yy - H / 2) ** 2) / (W / 2) ** 2) ** 1.6, 0.5, 1)[..., None].astype(np.float32)

proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}',
                         '-r', str(FPS), '-i', '-', '-i', AUDIO, '-map', '0:v', '-map', '1:a',
                         '-c:v', 'libx264', '-preset', 'slow', '-b:v', '11M', '-maxrate', '15M', '-bufsize', '22M',
                         '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-t', str(DUR),
                         '-movflags', '+faststart', OUT], stdin=subprocess.PIPE)


def shot_at(n):
    return max(i for i, c in enumerate(CUTF[:-1]) if c <= n)


def render_base(k, n):
    li = n - CUTF[k]
    lowfps = not (df <= n < F(KICK_B[-1]))  # groove + roll + outro low-fps, drop full fps
    src, off, sp, look, crop = SHOTS[k]
    img = src_frame(k, li, lowfps).astype(np.float32) / 255
    return grade(img, look, n), look


prev = None
pdx = pdy = prot = 0.0
for n in range(NFR):
    k = shot_at(n)
    li = n - CUTF[k]
    img, look = render_base(k, n)
    names = [o[0] for o in ofx[n]]

    if 'mix' in names:  # A/B flicker with the previous shot
        if k > 0:
            other, _ = render_base(k - 1, CUTF[k] - 1)
            img = other if ofx[n][names.index('mix')][1] == 0 else img * 0.5 + other * 0.5

    # camera
    z = zm[n]
    if k == END_SHOT:
        z *= 1 + 0.2 * li / max(NFR - CUTF[k], 1)
    R = cv2.getRotationMatrix2D((0, 0), rot[n], z * W / SW * 1.12)[:, :2]
    A2 = np.diag([stx[n], sty[n]]) @ R
    b = np.array([W / 2 + dx[n], H / 2 + dy[n]]) - A2 @ np.array([SW / 2, SW / 2])
    M = np.hstack([A2, b[:, None]])
    img = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

    # motion blur from camera velocity
    vx, vy, vr = dx[n] - pdx, dy[n] - pdy, rot[n] - prot
    pdx, pdy, prot = dx[n], dy[n], rot[n]
    img = vec_blur(img, vx * 0.45, vy * 0.45)
    img = spin_blur(img, vr * 0.5)
    if zm[n] > 1.03 or zm[n] < 0.97:
        img = zoom_blur(img, abs(zm[n] - 1) * 0.35)

    # one-framers
    for name, i, A in ofx[n]:
        if name == 'flash':
            img = img + [1.0, 0.5, 0.18][i] * min(A, 1.0)
        elif name == 'black':
            img = img * 0.05
        elif name == 'inv':
            img = 1 - np.clip(img, 0, 1)
        elif name == 'hblur':
            img = line_blur(img, [140, 60][i] * A, True)
        elif name == 'vblur':
            img = line_blur(img, [120, 50][i] * A, False)
        elif name == 'zblur':
            img = zoom_blur(img, [0.35, 0.15][i] * min(A, 1.2))
        elif name == 'mosaic':
            img = mosaic(img, [36, 16][i])
        elif name == 'hue':
            img = hue_poster(img, 60 + 50 * i)
        elif name == 'kaleido':
            img = kaleido(img) if i == 0 else kaleido(img[:, ::-1])
        elif name == 'rgb':
            img = rgb_split(img, [34, 16][i] * A, ang=rng.uniform(0, math.pi))
        elif name == 'slices':
            img = slices(img, A)
        elif name == 'thresh':
            g = img.mean(2, keepdims=True)
            img = np.repeat((g > 0.45).astype(np.float32), 3, 2)
        elif name == 'ghost' and prev is not None:
            sh = np.roll(prev, (int(rng.normal(0, 40)), int(rng.normal(0, 40))), axis=(0, 1))
            img = img * 0.55 + sh * 0.45

    # ghost on cuts (quick cross-frame like the refs)
    if prev is not None and li == 0 and n not in (df,):
        img = img * 0.72 + prev * 0.28

    # drop: one black frame before, then flash
    if n == df - 1:
        img = img * 0.0
    if k == END_SHOT:
        img = img * max(0.0, min(1.0, (NFR - n) / (0.5 * FPS)))

    img = np.clip(img, 0, 1) * VIG
    img = np.clip(img + rng.normal(0, 0.03, (H, W, 1)).astype(np.float32), 0, 1)
    prev = img
    proc.stdin.write((img * 255).astype(np.uint8).tobytes())
    if n % 75 == 0:
        print(n, '/', NFR, flush=True)
proc.stdin.close()
proc.wait()
print('done', OUT)
