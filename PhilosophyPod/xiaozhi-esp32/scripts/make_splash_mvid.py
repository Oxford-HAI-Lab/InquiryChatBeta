#!/usr/bin/env python3
"""Pack a video into a JPEG-sequence file for the boot splash player.

Output format (little-endian):
  Offset 0  : magic 'MVID' (4 bytes)
  Offset 4  : uint16 frame_count
  Offset 6  : uint16 width
  Offset 8  : uint16 height
  Offset 10 : uint16 delay_ms
  Offset 12 : uint32 offsets[frame_count + 1]  (last entry = end-of-data)
  Offset .. : raw JPEG bytes for each frame
"""
import argparse, glob, json, os, struct, subprocess, sys, tempfile

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('output')
    ap.add_argument('--width', type=int, required=True)
    ap.add_argument('--height', type=int, required=True)
    ap.add_argument('--fps', type=int, default=20)
    ap.add_argument('--quality', type=int, default=4, help='ffmpeg -q:v (2-31, lower=better)')
    args = ap.parse_args()

    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                            '-show_entries', 'stream=width,height',
                            '-of', 'json', args.input],
                           capture_output=True, text=True, check=True)
    info = json.loads(probe.stdout)['streams'][0]
    sw, sh = int(info['width']), int(info['height'])
    scale = max(args.width / sw, args.height / sh)
    new_w = int(round(sw * scale))
    new_h = int(round(sh * scale))
    crop_x = (new_w - args.width) // 2
    crop_y = (new_h - args.height) // 2

    with tempfile.TemporaryDirectory() as td:
        pat = os.path.join(td, 'f_%04d.jpg')
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', args.input,
                        '-vf', (f'scale={new_w}:{new_h}:flags=lanczos,'
                                f'crop={args.width}:{args.height}:{crop_x}:{crop_y},'
                                f'fps={args.fps}'),
                        '-q:v', str(args.quality), pat], check=True)

        frames = sorted(glob.glob(os.path.join(td, '*.jpg')))
        count = len(frames)
        delay_ms = int(round(1000 / args.fps))

        header_size = 4 + 2 + 2 + 2 + 2 + (count + 1) * 4
        offsets = []
        cursor = header_size
        for f in frames:
            offsets.append(cursor)
            cursor += os.path.getsize(f)
        offsets.append(cursor)

        with open(args.output, 'wb') as out:
            out.write(b'MVID')
            out.write(struct.pack('<HHHH', count, args.width, args.height, delay_ms))
            for off in offsets:
                out.write(struct.pack('<I', off))
            for f in frames:
                with open(f, 'rb') as fp:
                    out.write(fp.read())

    print(f'Wrote {args.output}: {count} frames {args.width}x{args.height} '
          f'@ {delay_ms}ms/frame, total {os.path.getsize(args.output)/1024:.1f} KB')

if __name__ == '__main__':
    main()
