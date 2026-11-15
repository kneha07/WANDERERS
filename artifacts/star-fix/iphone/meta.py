# Read iPhone HEIC metadata. GPS position goes to answer_key.json only (not printed), so it cannot steer the estimate.
import sys, glob, io, json, struct, os
import pillow_heif, exifread
from PIL import Image
pillow_heif.register_heif_opener()
def apple_makernote(raw):
    """Parse Apple MakerNote IFD; return {tag: value}. Offsets are relative to the MakerNote start."""
    i = raw.find(b'Apple iOS\x00')
    if i < 0: return {}
    mn = raw[i:]; bo = '>' if mn[12:14] == b'MM' else '<'
    n = struct.unpack(bo + 'H', mn[14:16])[0]; out = {}
    for k in range(n):
        tag, typ, cnt, val = struct.unpack(bo + 'HHII', mn[16 + 12*k: 28 + 12*k])
        if typ in (5, 10):                                 # (S)RATIONAL
            fmt = bo + ('ii' if typ == 10 else 'II') * cnt
            nums = struct.unpack(fmt, mn[val: val + 8*cnt])
            out[tag] = [nums[j] / nums[j+1] if nums[j+1] else None for j in range(0, len(nums), 2)]
        elif typ in (3, 4, 8, 9) and cnt == 1:
            out[tag] = val >> 16 if (typ in (3, 8) and bo == '>') else val
    return out
key = {}
for f in sorted(glob.glob(sys.argv[1] + '/*.heic')):
    name = os.path.basename(f)[:-9]
    im = Image.open(f); raw = im.info.get('exif', b'')
    t = exifread.process_file(io.BytesIO(raw[6:] if raw[:4] == b'Exif' else raw), details=False)
    g = lambda k: str(t.get(k, '')) or None
    key[name] = {k: g(k) for k in ('GPS GPSLatitude', 'GPS GPSLatitudeRef', 'GPS GPSLongitude', 'GPS GPSLongitudeRef', 'GPS GPSAltitude')}
    mn = apple_makernote(raw)
    print(f"{name}: {g('EXIF DateTimeOriginal')} {g('EXIF OffsetTimeOriginal')} | {g('Image Model')} | {g('EXIF LensModel')} | "
          f"f35={g('EXIF FocalLengthIn35mmFilm')} exp={g('EXIF ExposureTime')} ISO={g('EXIF ISOSpeedRatings')} | size {im.size} | "
          f"heading={g('GPS GPSImgDirection')} {g('GPS GPSImgDirectionRef')} | gps_present={key[name]['GPS GPSLatitude'] is not None} | "
          f"accel(0x08)={mn.get(8)}")
    im.thumbnail((1600, 1600)); im.convert('RGB').save(f'heic/{name}.jpg', quality=85)
json.dump(key, open('answer_key.json', 'w'), indent=1)
