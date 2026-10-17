"""Executed only inside the networkless, read-only image sandbox."""
import sys,resource,warnings
resource.setrlimit(resource.RLIMIT_CPU,(10,10))
resource.setrlimit(resource.RLIMIT_FSIZE,(16000000,16000000))
from PIL import Image
from io import BytesIO
warnings.simplefilter('error',Image.DecompressionBombWarning)
Image.MAX_IMAGE_PIXELS=16000000
raw=sys.stdin.buffer.read(50000001)
if len(raw)>50000000:raise ValueError('Oversized input')
with Image.open(BytesIO(raw)) as im:
    if im.format not in ('PNG','JPEG','GIF','WEBP','AVIF') or min(im.size)<8 or im.width*im.height>16000000:
        raise ValueError('Unsupported image or dimensions')
    im.seek(0);im.load();im.thumbnail((1600,1600))
    out=BytesIO();im.convert('RGB').save(out,format='PNG')
    sys.stdout.buffer.write(out.getvalue())
