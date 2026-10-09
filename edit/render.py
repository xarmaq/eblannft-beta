"""Ledger jugg edit v2: frame-accurate beat cuts, stepped (jerky) shakes, no text."""
import subprocess, sys, math, os
import numpy as np, cv2

S = os.path.dirname(os.path.abspath(__file__))
V = S + '/dl/v/'
I = S + '/dl/img/'
AUDIO = '/root/.claude/uploads/62bc846c-ac5e-5d9d-8492-e1f229c16b72/dea228f0-ssstik.io_1791554239751.mp3'
OUT = sys.argv[1] if len(sys.argv) > 1 else S + '/out2.mp4'
W = H = 1080
FPS = 30
DUR = 12.45
SW = 1300  # working size with margin for shake / rotation

# measured from the track (kick band onset peaks)
KICK_A = [0.139, 0.662, 1.167, 1.834, 2.339, 2.844, 3.349, 3.849, 4.516, 5.021]
ROLL = [5.631, 5.747, 5.985, 6.113, 6.264, 6.409, 6.560, 6.658, 6.774, 6.966, 7.070]
DROP = 7.187
KICK_B = [7.187, 7.709, 8.214, 8.719, 9.218, 9.898, 10.391, 10.890, 11.389, 11.894]
SNARE = [0.789, 4.981, 5.492, 7.976, 9.334, 10.507]  # small jerks without a cut


def F(t):
    return int(round(t * FPS))


# shots: (source, offset, speed, look, crop(cx, cy, zoom), flags)
# crop is in source-normalised coords; zoom>1 crops tighter (used to cut subtitles away)
C17 = (0.5, 0.44, 1.25)
SHOTS_A = [
    ('v17.mp4', 0.2, 0.8, 'hot', (0.45, 0.42, 1.2), ''),     # seed phrases burning
    ('v17.mp4', 11.0, 1.0, 'cold', C17, ''),                 # vault drawer
    ('v17.mp4', 26.9, 1.0, 'cold', (0.55, 0.45, 1.15), ''),   # nano x flying through paper
    ('v4.mp4', 0.8, 1.0, 'mono', None, ''),                  # stax exploded
    ('v7.mp4', 2.4, 1.0, 'cold', (0.5, 0.45, 1.3), ''),       # bitcoin particles
    ('v17.mp4', 61.0, 1.0, 'cold', C17, ''),                 # nano in hand, dark
    ('v9.mp4', 1.0, 1.4, 'mono', None, 'tilt'),              # flex stack
    ('v17.mp4', 38.3, 1.0, 'gold', C17, ''),                 # gold vault cubes
    ('v16.mp4', 10.4, 1.3, 'warm', (0.5, 0.62, 1.0), ''),     # phone + flex on table
    ('v17.mp4', 52.4, 1.0, 'cold', C17, 'echo'),             # face silhouette
]
SHOTS_ROLL = [  # stills / short bursts flicker on each roll hit
    ('i1.png', 0, 1, 'bw', None, ''),
    ('v4.mp4', 1.6, 1, 'bwinv', None, ''),
    ('i3.png', 0, 1, 'bw', None, ''),
    ('v17.mp4', 27.4, 1, 'bwinv', (0.55, 0.45, 1.15), ''),
    ('i2.png', 0, 1, 'bw', None, ''),
    ('v19.webm', 5.0, 1, 'bwinv', None, ''),
    ('i4.png', 0, 1, 'bw', None, ''),
    ('v9.mp4', 3.0, 1, 'bwinv', None, ''),
    ('i2.png', 0, 1, 'bw', None, ''),
    ('v11.mp4', 2.0, 1, 'bwinv', None, ''),
    ('i1.png', 0, 1, 'bw', None, ''),
]
SHOTS_B = [
    ('i1.png', 0, 1, 'cold', None, 'hero'),                  # DROP: nano x
    ('v19.webm', 4.0, 1.4, 'cold', None, ''),
    ('v3.mp4', 3.6, 1.2, 'cold', None, ''),
    ('v17.mp4', 57.0, 1.0, 'gold', C17, ''),                 # glass vault box
    ('i3.png', 0, 1, 'mono', None, 'tilt'),                  # flex
    ('v11.mp4', 1.8, 1.0, 'mono', None, ''),                 # stax + phone
    ('v7.mp4', 0.4, 1.0, 'cold', (0.5, 0.5, 1.2), ''),        # bitcoin particles rising
    ('v15.mp4', 0.6, 1.0, 'cold', None, 'tilt'),
    ('i4.png', 0, 1, 'cold', None, ''),                      # nano gen5
    ('v17.mp4', 27.2, 0.45, 'mono', (0.55, 0.45, 1.15), 'end'),  # outro slow-mo nano x
]

TIMELINE = []  # (start_frame, end_frame, shot, kind)
cuts = [0.0] + KICK_A[1:] + ROLL + KICK_B + [DUR]
shots = SHOTS_A + SHOTS_ROLL + SHOTS_B
assert len(shots) == len(cuts) - 1, (len(shots), len(cuts))
for k, sh in enumerate(shots):
    kind = 'A' if k < len(SHOTS_A) else ('R' if k < len(SHOTS_A) + len(SHOTS_ROLL) else 'B')
    TIMELINE.append((F(cuts[k]), F(cuts[k + 1]), sh, kind))
NFR = F(DUR)


def load_video(name, off, frames_needed, speed, crop):
    cx, cy, z = crop or (0.5, 0.5, 1.0)
    need = frames_needed / FPS * speed + 0.3
    vf = (f"crop=w='min(iw,ih)/{z}':h='min(iw,ih)/{z}':"
          f"x='clip({cx}*iw-ow/2,0,iw-ow)':y='clip({cy}*ih-oh/2,0,ih-oh)',"
          f"scale={SW}:{SW},fps={FPS / speed}")
    cmd = ['ffmpeg', '-v', 'error', '-ss', str(off), '-t', str(need), '-i', V + name,
           '-vf', vf, '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, SW, SW, 3)


def load_still(name):
    im = cv2.imread(I + name)
    h, w = im.shape[:2]
    side = int(h * 0.86)  # device sits on the right, product name on the left
    x0 = max(0, min(w - side, int(w * 0.84) - side // 2))
    y0 = (h - side) // 2
    return cv2.resize(im[y0:y0 + side, x0:x0 + side], (SW, SW), interpolation=cv2.INTER_CUBIC)[None]


cache = {}


def frames_for(k):
    if k not in cache:
        s, e, (src, off, sp, look, crop, fl), kind = TIMELINE[k]
        cache[k] = load_still(src) if src.endswith('.png') else load_video(src, off, e - s, sp, crop)
    return cache[k]


def grade(f, look, flash_col):
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
    if flash_col == 'hue':
        hsv = cv2.cvtColor((np.clip(f, 0, 1) * 255).astype(np.uint8), cv2.COLOR_BGR2HSV)
        hsv[..., 0] = (hsv[..., 0].astype(np.int32) + 75) % 180
        hsv[..., 1] = np.clip(hsv[..., 1].astype(np.int32) * 3 + 120, 0, 255)
        f = np.round(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR).astype(np.float32) / 255 * 4) / 4
    elif flash_col == 'inv':
        f = 1 - np.clip(f, 0, 1)
    f = np.clip(f, 0, 1)
    return f * f * (3 - 2 * f) * 0.7 + f * 0.3  # contrast curve


def radial_blur(img, amount, n=6):
    if amount < 0.008:
        return img
    acc = img.copy()
    for i in range(1, n):
        Mx = cv2.getRotationMatrix2D((W / 2, H / 2), 0, 1 + amount * i / n)
        acc += cv2.warpAffine(img, Mx, (W, H), borderMode=cv2.BORDER_REFLECT)
    return acc / n


def dir_blur(img, dx, dy):
    L = math.hypot(dx, dy)
    if L < 3:
        return img
    L = min(int(L), 61) | 1
    k = np.zeros((L, L), np.float32)
    c = L // 2
    ux, uy = dx / math.hypot(dx, dy), dy / math.hypot(dx, dy)
    for i in range(L):
        s = i - c
        k[int(round(c + s * uy)), int(round(c + s * ux))] = 1
    return cv2.filter2D(img, -1, k / k.sum(), borderType=cv2.BORDER_REFLECT)


def rgb_split(img, px, ang=0.0):
    px = int(px)
    if px < 1:
        return img
    dx, dy = int(px * math.cos(ang)), int(px * math.sin(ang))
    out = img.copy()
    out[..., 2] = np.roll(img[..., 2], (dy, dx), axis=(0, 1))
    out[..., 0] = np.roll(img[..., 0], (-dy, -dx), axis=(0, 1))
    return out


# ---------- stepped shake track ----------
# every hit spawns a burst: a new random offset on every frame, decaying fast,
# so the camera snaps between positions instead of gliding (AE "wiggle" with posterized time).
rng = np.random.default_rng(11)
sx = np.zeros(NFR + 8); sy = np.zeros(NFR + 8); sr = np.zeros(NFR + 8)
zoom = np.zeros(NFR + 8); split = np.zeros(NFR + 8)


def burst(t, amp, rot, z, frames=7, decay=0.6, spl=0.0):
    f0 = F(t)
    ang = rng.uniform(0, 2 * math.pi)
    sign = rng.choice([-1, 1])
    for i in range(frames):
        if f0 + i >= NFR:
            break
        a = amp * decay ** i
        # alternate direction each frame (jerk back and forth) + random jitter
        ang += math.pi + rng.uniform(-0.9, 0.9)
        sx[f0 + i] += a * math.cos(ang)
        sy[f0 + i] += a * math.sin(ang)
        sr[f0 + i] += rot * decay ** i * (sign if i % 2 == 0 else -sign)
        zoom[f0 + i] = max(zoom[f0 + i], z * (0.45 ** i))
        split[f0 + i] = max(split[f0 + i], spl * 0.55 ** i)


for t in KICK_A:
    burst(t, 46, 3.0, 0.26, spl=14)
for t in SNARE:
    burst(t, 20, 1.2, 0.06, frames=4, spl=8)
for j, t in enumerate(ROLL):
    g = (j + 1) / len(ROLL)
    burst(t, 18 + 46 * g, 1 + 4 * g, 0.12 + 0.14 * g, frames=4, decay=0.55, spl=6 + 16 * g)
for t in KICK_B:
    burst(t, 78, 5.5, 0.34, frames=8, spl=26)
burst(DROP, 120, 8, 0.5, frames=10, decay=0.68, spl=40)
# constant low jitter, updated every 2 frames (choppy handheld)
for n in range(0, NFR, 2):
    jx, jy = rng.normal(0, 3.5, 2)
    sx[n:n + 2] += jx; sy[n:n + 2] += jy

yy, xx = np.mgrid[0:H, 0:W]
VIG = np.clip(1 - 0.3 * (((xx - W / 2) ** 2 + (yy - H / 2) ** 2) / (W / 2) ** 2) ** 1.6, 0.5, 1)[..., None].astype(np.float32)

proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}',
                         '-r', str(FPS), '-i', '-', '-i', AUDIO, '-map', '0:v', '-map', '1:a',
                         '-c:v', 'libx264', '-preset', 'slow', '-b:v', '10M', '-maxrate', '14M', '-bufsize', '20M',
                         '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-t', str(DUR),
                         '-movflags', '+faststart', OUT], stdin=subprocess.PIPE)

prev = None
px_prev, py_prev = 0.0, 0.0
roll_start, drop_f = F(ROLL[0]), F(DROP)
for n in range(NFR):
    k = max(i for i, seg in enumerate(TIMELINE) if seg[0] <= n)
    s, e, (src, off, sp, look, crop, fl), kind = TIMELINE[k]
    li = n - s  # frame within shot
    fr = frames_for(k)
    if len(fr) == 1:
        base = fr[0]
    else:
        # velocity ramp: punch through the first frames, then ease (kept as frame steps)
        if kind == 'B' and 'end' not in fl:
            idx = int(li * 1.8) if li < 4 else int(7 + (li - 4) * 0.7)
        else:
            idx = li
        base = fr[min(idx, len(fr) - 1)]
    img = base.astype(np.float32) / 255

    # colour flashes on the first frames of drop cuts
    flash_col = None
    if kind == 'B' and 'end' not in fl and li < 2:
        flash_col = 'hue' if (k % 2 == 0) == (li == 0) else 'inv'
    img = grade(img, look, flash_col)

    # camera
    z = 1.0 + zoom[n]
    if fl in ('hero',) or 'end' in fl:
        z += 0.18 * li / max(e - s, 1)
    if kind == 'R':  # roll: continuous push-in across the whole build
        z += 0.45 * (n - roll_start) / (drop_f - roll_start)
    rot = sr[n]
    if 'tilt' in fl:
        rot += (7 if k % 2 else -7) * min(1, li / 4)  # snap into a dutch angle
    Mx = cv2.getRotationMatrix2D((SW / 2, SW / 2), rot, z * W / SW * 1.12)
    Mx[0, 2] += sx[n] - (SW - W) / 2
    Mx[1, 2] += sy[n] - (SW - H) / 2
    img = cv2.warpAffine(img, Mx, (W, H), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT if 'tilt' in fl else cv2.BORDER_REFLECT)

    # motion blur along the jerk, zoom blur on punches
    img = dir_blur(img, (sx[n] - px_prev) * 0.5, (sy[n] - py_prev) * 0.5)
    px_prev, py_prev = sx[n], sy[n]
    img = radial_blur(img, zoom[n] * 0.45)
    img = rgb_split(img, split[n], ang=math.atan2(sy[n], sx[n] + 1e-6))

    # ghosting
    if prev is not None:
        if 'echo' in fl:
            img = img * 0.6 + prev * 0.4
        elif li == 0 and kind != 'R':
            img = img * 0.7 + prev * 0.3

    # flashes / black frames
    if n == drop_f - 1:
        img = img * 0.0  # one black frame right before the drop
    if 0 <= n - drop_f < 4:
        img = img + [1.0, 0.7, 0.35, 0.12][n - drop_f]
    if kind == 'B' and li == 0 and n != drop_f and 'end' not in fl:
        img = img + 0.22
    if kind == 'A' and n == F(KICK_A[0]):
        img = img + 0.8
    if kind == 'A' and n == F(KICK_A[0]) + 1:
        img = img + 0.3
    if kind == 'R' and li == 0:
        img = img + 0.15 * (1 + (n - roll_start) / (drop_f - roll_start))
    if 'end' in fl:
        img = img * max(0.0, min(1.0, (NFR - n) / (0.5 * FPS)))

    img = np.clip(img, 0, 1) * VIG
    img = img + rng.normal(0, 0.03, (H, W, 1)).astype(np.float32)
    img = np.clip(img, 0, 1)
    prev = img
    proc.stdin.write((img * 255).astype(np.uint8).tobytes())
    if n % 75 == 0:
        print(n, '/', NFR, flush=True)
proc.stdin.close()
proc.wait()
print('done', OUT)
