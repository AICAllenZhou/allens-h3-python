"""Command line interface — for people who do not write Python.

    allens-h3 health
    allens-h3 gpu
    allens-h3 generate --prompt "A cinematic commercial" --duration 5 \
                       --output output.mp4
    allens-h3 status <job_id>
    allens-h3 cancel <job_id>
    allens-h3 download <job_id> --output video.mp4

Credentials come from ALLENS_H3_API_KEY / ALLENS_H3_BASE_URL, never from a
command-line flag — arguments are visible in shell history and process lists.
"""

from __future__ import annotations

import argparse
import json
import sys

from .client import H3Client
from .exceptions import H3Error
from .models import Job
from .version import __title__, __version__


def _client() -> H3Client:
    return H3Client()


def _progress(job: Job) -> None:
    sys.stderr.write(f"\r  {job.status:<11} {job.percent:5.1f}%   ")
    sys.stderr.flush()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="allens-h3", description=f"{__title__} v{__version__}",
        epilog="Set ALLENS_H3_BASE_URL and ALLENS_H3_API_KEY before use.")
    ap.add_argument("--version", action="version",
                    version=f"allens-h3 {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("health", help="check that the service is up")
    sub.add_parser("gpu", help="show GPU telemetry")

    g = sub.add_parser("generate", help="generate a video and download it")
    g.add_argument("--prompt", required=True)
    g.add_argument("--width", type=int, default=608)
    g.add_argument("--height", type=int, default=352)
    g.add_argument("--duration", type=float, default=5.0)
    g.add_argument("--steps", type=int, default=20)
    g.add_argument("--seed", type=int)
    g.add_argument("--output", "-o", default="output.mp4")
    g.add_argument("--timeout", type=float, default=1800)

    s = sub.add_parser("status", help="show one job")
    s.add_argument("job_id")

    c = sub.add_parser("cancel", help="cancel a job")
    c.add_argument("job_id")

    d = sub.add_parser("download", help="download a finished job")
    d.add_argument("job_id")
    d.add_argument("--output", "-o", default="output.mp4")

    lj = sub.add_parser("jobs", help="list recent jobs")
    lj.add_argument("--limit", type=int, default=20)

    args = ap.parse_args(argv)

    try:
        with _client() as client:
            if args.command == "health":
                h = client.health()
                print(json.dumps(h.raw, indent=2))
                return 0 if h.is_ok else 1

            if args.command == "gpu":
                g_ = client.gpu()
                print(f"{g_.name}")
                print(f"  temperature  {g_.temperature_c} C")
                if g_.hotspot_c is not None:
                    print(f"  hotspot      {g_.hotspot_c} C")
                if g_.vram_max_c is not None:
                    print(f"  vram hottest {g_.vram_max_c} C")
                print(f"  power        {g_.power_w} W / {g_.power_limit_w} W")
                print(f"  vram         {g_.vram_used_mb} / {g_.vram_total_mb} MB")
                print(f"  worker       {g_.worker}  queue={g_.queue_depth}")
                return 0

            if args.command == "generate":
                print(f"submitting: {args.prompt[:70]}...", file=sys.stderr)
                video = client.generate(
                    prompt=args.prompt, width=args.width, height=args.height,
                    duration=args.duration, steps=args.steps, seed=args.seed,
                    timeout=args.timeout, on_progress=_progress)
                sys.stderr.write("\n")
                path = video.download(args.output)
                print(f"job     {video.job_id}")
                print(f"saved   {path}")
                return 0

            if args.command == "status":
                j = client.get_job(args.job_id)
                print(json.dumps(j.raw, indent=2))
                return 0

            if args.command == "cancel":
                j = client.cancel(args.job_id)
                print(f"{j.id}: {j.status}")
                return 0

            if args.command == "download":
                path = client.download(args.job_id, args.output)
                print(f"saved   {path}")
                return 0

            if args.command == "jobs":
                for j in client.list_jobs(args.limit):
                    print(f"{j.id}  {j.status:<11} {j.percent:5.1f}%")
                return 0

    except H3Error as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130

    return 1


if __name__ == "__main__":
    sys.exit(main())
