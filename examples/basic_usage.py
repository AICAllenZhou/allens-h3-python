"""Allen's MiniMax H3 API — worked examples.

Run the whole file:

    python example.py

Or one section at a time:

    python example.py basic
    python example.py progress
    python example.py errors
    python example.py batch
    python example.py async

Before running, set both environment variables (see CLIENT-SETUP.md):

    ALLENS_H3_BASE_URL   the current tunnel URL
    ALLENS_H3_API_KEY    your personal key

Note the endpoint is never written into this file. The tunnel hostname
changes whenever the server restarts, so it always comes from the
environment — copy that habit into your own scripts.
"""

from __future__ import annotations

import sys

from allens_h3 import (
    H3AuthenticationError,
    H3Client,
    H3Error,
    H3GPUUnavailableError,
    H3JobFailedError,
    H3RateLimitError,
    H3TimeoutError,
    H3ValidationError,
)


# --------------------------------------------------------------------------
def example_basic() -> None:
    """The shortest useful program: prompt in, MP4 out."""
    print("\n=== basic ===")

    client = H3Client()          # reads ALLENS_H3_BASE_URL / ALLENS_H3_API_KEY

    video = client.generate(
        prompt="A cinematic BBA AI commercial: young professionals "
               "collaborating in a bright modern office, warm natural light, "
               "slow dolly-in, shallow depth of field.",
        duration=5,
    )

    path = video.download("output.mp4")
    print(f"saved {path}")


# --------------------------------------------------------------------------
def example_progress() -> None:
    """Show a live progress bar while the GPU works."""
    print("\n=== progress ===")

    client = H3Client()

    def on_progress(job) -> None:
        filled = int(job.progress * 30)
        bar = "#" * filled + "-" * (30 - filled)
        sys.stdout.write(f"\r  [{bar}] {job.percent:5.1f}%  {job.status}")
        sys.stdout.flush()

    video = client.generate(
        prompt="A cinematic close-up of raindrops on a window at night, "
               "neon reflections, shallow depth of field.",
        duration=5,
        on_progress=on_progress,
    )
    print()
    print(f"saved {video.download('rain.mp4')}")


# --------------------------------------------------------------------------
def example_errors() -> None:
    """Handle every failure mode explicitly.

    Each server condition maps to its own exception type, so you never have to
    inspect a status code.
    """
    print("\n=== error handling ===")

    client = H3Client()

    try:
        video = client.generate(prompt="A cinematic product shot", duration=5)
        print(f"saved {video.download('product.mp4')}")

    except H3AuthenticationError:
        print("Your key is wrong, revoked, or expired. Ask Allen for a new one.")

    except H3ValidationError as e:
        print(f"The request was rejected: {e}")

    except H3RateLimitError as e:
        wait = f" Retry in {e.retry_after:.0f}s." if e.retry_after else ""
        print(f"You hit a rate limit.{wait}")

    except H3GPUUnavailableError:
        print("The GPU is busy or too hot. Try again in a few minutes.")

    except H3JobFailedError as e:
        print(f"Job {e.job_id} ended as {e.job_status}. Retry once; if it "
              f"fails again send Allen the job id.")

    except H3TimeoutError:
        print("Still running past the timeout — it may yet finish. "
              "Use client.get_job(job_id) to keep checking.")

    except H3Error as e:
        # Base class: catches anything not handled above.
        print(f"Unexpected error: {e}")


# --------------------------------------------------------------------------
def example_batch() -> None:
    """Submit several jobs, then collect them.

    The server runs exactly one job on the GPU at a time and queues the rest,
    so submitting a batch is safe — it will not overload the card.
    """
    print("\n=== batch ===")

    client = H3Client()

    prompts = [
        "A cinematic wide shot of a robotics classroom, warm afternoon light",
        "A close-up of a robot arm placing a component, shallow depth of field",
        "A slow pan across students presenting an AI project on a large screen",
    ]

    # submit everything first, without waiting
    jobs = []
    for i, prompt in enumerate(prompts, 1):
        job = client.create_video(prompt=prompt, duration=5)
        jobs.append(job)
        print(f"  submitted {i}/{len(prompts)}: {job.id}")

    # then collect each result
    for i, job in enumerate(jobs, 1):
        try:
            done = client.wait(job.id)
            path = client.download(done.id, f"batch_{i}.mp4")
            print(f"  finished {i}/{len(jobs)}: {path.name}")
        except H3Error as e:
            print(f"  job {i} failed: {e}")


# --------------------------------------------------------------------------
def example_manual_polling() -> None:
    """Fire and forget: submit now, collect later.

    Useful in a web backend, where you do not want to hold a request open for
    five minutes.
    """
    print("\n=== manual polling ===")

    client = H3Client()

    job = client.create_video(prompt="A cinematic city skyline at dusk",
                              duration=5)
    print(f"  job {job.id} submitted; store this id and return to the user")

    # ... later, in another request or a worker ...
    import time
    while True:
        job = client.get_job(job.id)
        print(f"  {job.status} {job.percent}%")
        if job.is_terminal:
            break
        time.sleep(10)

    if job.is_complete:
        print(f"  saved {client.download(job.id, 'skyline.mp4')}")
    else:
        print(f"  ended as {job.status}: {job.error}")


# --------------------------------------------------------------------------
def example_status() -> None:
    """Check the service and the GPU before committing to a long job."""
    print("\n=== status ===")

    client = H3Client()

    health = client.health()
    print(f"  service : {health.status}  comfyui={health.comfyui}  "
          f"worker={health.worker}")

    if not health.is_ok:
        print("  service is not healthy; skipping generation")
        return

    gpu = client.gpu()
    print(f"  gpu     : {gpu.name}")
    print(f"  temp    : {gpu.temperature_c} C  (hotspot {gpu.hotspot_c} C)")
    print(f"  power   : {gpu.power_w} W / {gpu.power_limit_w} W")
    print(f"  queue   : {gpu.queue_depth} waiting, worker is {gpu.worker}")

    for job in client.list_jobs(limit=5):
        print(f"  recent  : {job.id}  {job.status}")


# --------------------------------------------------------------------------
async def example_async() -> None:
    """Async client — same methods, awaited.

    Generating three clips concurrently still runs them one at a time on the
    GPU; the benefit is that your event loop is not blocked.
    """
    print("\n=== async ===")

    import asyncio

    from allens_h3 import AsyncH3Client

    async with AsyncH3Client() as client:
        health = await client.health()
        print(f"  service: {health.status}")

        results = await asyncio.gather(
            client.generate(prompt="A cinematic sunrise over mountains",
                            duration=5),
            client.generate(prompt="A cinematic timelapse of city traffic",
                            duration=5),
            return_exceptions=True,
        )

        for i, r in enumerate(results, 1):
            if isinstance(r, Exception):
                print(f"  {i}: failed — {r}")
            else:
                path = await r.download(f"async_{i}.mp4")
                print(f"  {i}: saved {path.name}")


# --------------------------------------------------------------------------
EXAMPLES = {
    "basic": example_basic,
    "progress": example_progress,
    "errors": example_errors,
    "batch": example_batch,
    "polling": example_manual_polling,
    "status": example_status,
}


def main() -> int:
    choice = sys.argv[1] if len(sys.argv) > 1 else ""

    if choice == "async":
        import asyncio
        asyncio.run(example_async())
        return 0

    if choice in EXAMPLES:
        EXAMPLES[choice]()
        return 0

    if choice:
        print(f"unknown example: {choice}")
        print(f"choose one of: {', '.join(EXAMPLES)}, async")
        return 1

    # no argument: run the cheap ones only, so a curious first run does not
    # spend twenty minutes of GPU time
    print("Running status check only.")
    print(f"For a real generation run: python example.py basic")
    print(f"Available: {', '.join(EXAMPLES)}, async")
    example_status()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except H3Error as e:
        print(f"\nerror: {e}", file=sys.stderr)
        print("See CLIENT-SETUP.md for troubleshooting.", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
