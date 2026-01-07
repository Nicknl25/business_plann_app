import os

from api import create_app


def main() -> None:
  port_raw = os.getenv("BACKEND_PORT") or os.getenv("FLASK_RUN_PORT") or os.getenv("PORT") or "5050"
  try:
    port = int(str(port_raw).strip() or "5050")
  except Exception:
    port = 5050

  app = create_app()
  try:
    import unified_intake.draft_service as draft_service  # type: ignore

    print(f"ALIGNED_BACKEND=1 port={port} draft_service_file={draft_service.__file__}", flush=True)
  except Exception:
    print(f"ALIGNED_BACKEND=1 port={port} draft_service_file=?", flush=True)
  app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
  main()
