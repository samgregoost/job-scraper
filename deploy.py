#!/usr/bin/env python3
"""
Deploy Job Scraper Dashboard for remote access.

Usage:
    python deploy.py --ngrok              Expose via ngrok tunnel (instant, free)
    python deploy.py --local              Run on LAN only (accessible from same network)
    python deploy.py --ngrok --token YOUR_TOKEN   Use authenticated ngrok (stable URL)
"""

import argparse
import sys
import threading


def run_ngrok(port: int, token: str | None = None):
    """Start ngrok tunnel to expose the dashboard."""
    try:
        from pyngrok import ngrok, conf

        if token:
            ngrok.set_auth_token(token)

        # Start tunnel
        public_url = ngrok.connect(port, "http")
        print(f"\n{'='*60}")
        print(f"  Dashboard is live!")
        print(f"  Public URL:  {public_url}")
        print(f"  Local URL:   http://localhost:{port}")
        print(f"{'='*60}")
        print(f"  Share the public URL with anyone to give access.")
        print(f"  Press Ctrl+C to stop.\n")
        return public_url

    except Exception as e:
        print(f"Ngrok failed: {e}")
        print("Install ngrok: https://ngrok.com/download")
        print("Or sign up free at https://ngrok.com and run:")
        print(f"  python deploy.py --ngrok --token YOUR_AUTH_TOKEN")
        sys.exit(1)


def run_server(port: int, host: str):
    """Run the dashboard with a production-grade server."""
    try:
        from waitress import serve
        from dashboard import app

        print(f"Starting server on {host}:{port}...")
        serve(app, host=host, port=port, threads=4)
    except ImportError:
        from dashboard import app

        print(f"Starting Flask dev server on {host}:{port}...")
        print("(Install 'waitress' for production: pip install waitress)")
        app.run(host=host, port=port, debug=False)


def main():
    parser = argparse.ArgumentParser(description="Deploy Job Scraper Dashboard")
    parser.add_argument("--ngrok", action="store_true", help="Expose via ngrok tunnel")
    parser.add_argument("--local", action="store_true", help="LAN access only (0.0.0.0)")
    parser.add_argument("--token", type=str, default=None, help="Ngrok auth token")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")

    args = parser.parse_args()

    if not args.ngrok and not args.local:
        parser.print_help()
        print("\nExamples:")
        print("  python deploy.py --ngrok              # Public URL via ngrok")
        print("  python deploy.py --local              # LAN only")
        print("  python deploy.py --ngrok --token abc  # Stable ngrok URL")
        return

    port = args.port
    host = "0.0.0.0"

    if args.ngrok:
        # Start server in background thread
        server_thread = threading.Thread(
            target=run_server, args=(port, host), daemon=True
        )
        server_thread.start()

        # Start ngrok in foreground
        import time
        time.sleep(2)  # Wait for server to start
        run_ngrok(port, args.token)

        # Keep alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
            from pyngrok import ngrok
            ngrok.kill()

    elif args.local:
        import socket
        local_ip = socket.gethostbyname(socket.gethostname())
        print(f"\n{'='*60}")
        print(f"  Dashboard available on your network:")
        print(f"  http://{local_ip}:{port}")
        print(f"  http://localhost:{port}")
        print(f"{'='*60}\n")
        run_server(port, host)


if __name__ == "__main__":
    main()
