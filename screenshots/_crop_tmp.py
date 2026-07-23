from PIL import Image
import numpy as np

path = r"c:\Users\96655\Projects\369box\screenshots\main.png"
img = np.array(Image.open(path).convert("RGB"))
h, w = img.shape[:2]

def is_desktop(r, g, b):
    r, g, b = int(r), int(g), int(b)
    s = r + g + b
    if s >= 195:
        return True
    if r >= 120 and g >= 150 and b >= 165:
        return True
    if r <= 20 and 28 <= g <= 60 and 55 <= b <= 100:
        return True
    if r >= 35 and g >= 45 and b >= 55 and s >= 130 and r >= g - 5:
        return True
    return False

def row_outside_frac(y):
    return np.mean([is_desktop(*img[y, x]) for x in range(w)])

def col_outside_frac(x):
    return np.mean([is_desktop(*img[y, x]) for y in range(h)])

top = 0
for y in range(h):
    edge_desktop = is_desktop(*img[y, 0]) or is_desktop(*img[y, w // 2]) or is_desktop(*img[y, w - 1])
    if row_outside_frac(y) > 0.02 or (y < 3 and edge_desktop):
        top = y + 1
    else:
        break

for y in range(top, min(top + 20, h)):
    mid = img[y, w // 2]
    if mid.sum() < 100:
        top = y
        break

bottom = h - 1
for y in range(h - 1, -1, -1):
    if row_outside_frac(y) > 0.015:
        bottom = y - 1
    else:
        L, R = img[y, 0], img[y, w - 1]
        if is_desktop(*L) or is_desktop(*R):
            bottom = y - 1
        else:
            break

left = 0
for x in range(w):
    if col_outside_frac(x) > 0.02:
        left = x + 1
    else:
        break

right = w - 1
for x in range(w - 1, -1, -1):
    if col_outside_frac(x) > 0.02:
        right = x - 1
    else:
        break

y0, y1 = h // 4, 3 * h // 4
for x in range(left, w):
    col = img[y0:y1, x]
    frac = np.mean([is_desktop(*p) for p in col])
    if frac < 0.01:
        left = x
        break

for x in range(right, left, -1):
    col = img[y0:y1, x]
    frac = np.mean([is_desktop(*p) for p in col])
    if frac < 0.01:
        right = x
        break

print("bbox:", left, top, right, bottom)
print("Crop size:", right - left + 1, "x", bottom - top + 1)

for name, x, y in [
    ("tl", left, top), ("tm", (left+right)//2, top), ("tr", right, top),
    ("lm", left, (top+bottom)//2), ("rm", right, (top+bottom)//2),
    ("bl", left, bottom), ("bm", (left+right)//2, bottom), ("br", right, bottom),
]:
    p = img[y, x]
    print(f"post-{name}: RGB{tuple(int(c) for c in p)} desktop={is_desktop(*p)}")

cropped = img[top:bottom+1, left:right+1]
Image.fromarray(cropped).save(path)
print("Saved. Final size:", cropped.shape[1], "x", cropped.shape[0])
