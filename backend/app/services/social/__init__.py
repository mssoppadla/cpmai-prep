"""Social automation services: campaign scheduler + workflow runners.

The scheduler is an APScheduler instance owned by ``scheduler.py``,
started in the FastAPI lifespan. Workflow runners live in ``runners/``
— one class per workflow_type, registered in ``WORKFLOWS``.

External calls are deliberately minimal in this PR:
  * OpenAI text generation (admin already has the key configured)
  * FFmpeg (already in the backend container) for the auto-clip path
  * Whisper (OpenAI API) for transcription on the auto-clip path

NO direct posting to LinkedIn / Twitter / etc. Generated content lands
in the campaign_runs table and admin posts manually via /admin/social-queue.
A future ``providers.py`` module can swap that out for direct posting.
"""
